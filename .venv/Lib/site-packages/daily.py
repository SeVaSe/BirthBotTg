#!/usr/bin/env python3
import re
import pickle
import os.path
import subprocess
import json
import arrow
import click
from functools import cmp_to_key
from itertools import groupby
from halo import Halo
from dateutil import parser
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import gspread
import slack
import site

SHEETS_SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets',
]
CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.daily')
USER_CONFIG_PATH = os.path.join(CONFIG_DIR, 'user.json')
CLIENT_SECRET_FILE = os.path.join(site.USER_BASE, __name__, 'client_sheets.json')
SLACK_INFO_PROMPT = '''
Create a Slack app for your workspace and get the API token in the following page:
https://api.slack.com/custom-integrations/legacy-tokens
'''
STRIVELABS_TIMESHEET = 'TimeSheet StriveLabs'
STRIVELABS_PROJECT_NAME = 'StriveLabs'
TEMPLATE_FILE = os.path.join(site.USER_BASE, __name__, 'template.txt')


class ParsingError(Exception):
    pass


def create_git_log_command(since='midnight'):
    return f'git log --no-merges --since={since} --format="%s" --author="$(git config user.name)"'


def get_commits():
    command = create_git_log_command()
    result = subprocess.run(
        command, shell=True, capture_output=True, text=True)
    if result.returncode:
        return []
    lines = result.stdout.replace('"', '').split('\n')
    return list(filter(lambda line: line, lines))


def create_message_template():
    commits = get_commits()
    suggestions = '\n'.join(map(lambda commit: f'# - {commit}', commits))
    with open(TEMPLATE_FILE) as template:
        return template.read() + '\n' + suggestions
    return suggestions


def validate_working_hours(hours):
    pattern = re.compile(r'^(2[0-3]|[01]?[0-9]):([0-5]?[0-9])$')
    return all(map(pattern.match, hours))


def parse_working_hours(line):
    timestamps = line.replace(' ', '').replace('\n', '').split(',')
    result = list(map(lambda ts: ts if ':' in ts else f'{ts}:00', timestamps))
    if len(result) % 2 or not validate_working_hours(result):
        raise ParsingError('Invalid working hours')
    return result


def open_editor(contents=None):
    if not contents:
        template = create_message_template()
    return click.edit(template, extension='')


def preprocess_file(content):
    lines = [line.strip() for line in content.split('\n')]
    filtered_lines = filter(lambda line: line and not line.startswith('#'),
                            lines)
    return list(filtered_lines)


def create_daily_message(preprocessed_lines, date_format='Today'):
    now = arrow.utcnow()
    is_date_format = date_format.upper() != 'TODAY'
    header = now.format(date_format) if is_date_format else date_format
    body = ''
    for line in preprocessed_lines[1:]:
        if line.startswith('*'):
            body = body + f'\n\t{line}'
        elif line.startswith('-'):
            body = body + f'\n{line}'
        else:
            body = body + f'\n-{line}'
    return f'{header}:' + body


def create_description_for_timesheet(preprocessed_lines):
    lines = [
        line[1:].replace('.', '') for line in preprocessed_lines[1:]
        if not line.startswith('*')
    ]
    return '. '.join(lines).strip()


def get_credentials():
    credential_path = os.path.join(CONFIG_DIR, 'gsheet_token')
    credentials = None
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)
    if os.path.exists(credential_path):
        with open(credential_path, 'rb') as token:
            credentials = pickle.load(token)
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRET_FILE, SHEETS_SCOPES)
            credentials = flow.run_local_server(port=0)
        with open(credential_path, 'wb') as token:
            pickle.dump(credentials, token)
    credentials.access_token = credentials.token
    return credentials


def generate_project_config_filepath(project_name):
    filename = project_name.strip().replace(' ', '-')
    return os.path.join(CONFIG_DIR, f'{filename}.json')


def get_project_config(project_name):
    try:
        file_path = generate_project_config_filepath(project_name)
        with open(file_path, 'r') as config_file:
            return json.load(config_file)
    except FileNotFoundError:
        return None


def get_strivelabs_project_config(project_name):
    result = get_project_config(STRIVELABS_PROJECT_NAME)
    result["name"] = project_name
    return result


def get_user_config():
    result = None
    with open(USER_CONFIG_PATH, 'r') as config_file:
        result = json.load(config_file)
    return result


def post_message_on_slack(message, project_config):
    with Halo(text='Writing on Slack', spinner='dots') as spinner:
        error = None
        try:
            slack_client = slack.WebClient(token=project_config['slack_token'])
            response = slack_client.chat_postMessage(
                channel=project_config['channel'], text=message)
            if not response['ok'] or not response['message']['text'] == message:
                error = response
        except Exception as e:
            error = e.args[1]
        if error:
            spinner.fail(str(error))
        else:
            spinner.succeed('Writed on Slack')


def is_url(string):
    pattern = re.compile(r'^(?:http|ftp)s?://')
    return pattern.match(string) is not None


def parse_date(string):
    try:
        date = parser.parse(string)
        return arrow.get(date).floor('day')
    except Exception as e:
        return None


def find_cells_to_write(worksheet):
    date_cell = worksheet.find(re.compile('date', re.IGNORECASE))
    description_cell = worksheet.find(re.compile('description', re.IGNORECASE))
    dates_column = worksheet.col_values(date_cell.col)
    parsed_dates = [parse_date(date) for date in dates_column]
    today_row = -1
    today = arrow.utcnow().floor('day')
    for i, date in enumerate(parsed_dates):
        if today == date:
            today_row = i + 1
            break
    hours_cells = worksheet.range(today_row, date_cell.col + 1, today_row,
                                  date_cell.col + 6)
    return hours_cells, (today_row, description_cell.col, description_cell.value)


def parse_working_hour(hour):
    h1, m1 = hour.split(':')
    return int(h1), int(m1)


def hours_comparator(hour1, hour2):
    h1, m1 = parse_working_hour(hour1)
    h2, m2 = parse_working_hour(hour2)
    if h1 > h2 or (h1 == h2 and m1 > m2):
        return 1
    if h1 == h2 and m1 == m2:
        return 0
    return -1


def compute_total_hours(working_hours):
    minutes = 0
    for i in range(0, len(working_hours), 2):
        h1, m1 = parse_working_hour(working_hours[i])
        h2, m2 = parse_working_hour(working_hours[i + 1])
        minutes += (h2 * 60 + m2) - (h1 * 60 + m1)
    return (minutes // 60, minutes % 60)


def remove_consecutive_duplicates(l):
    result = []
    for k, group in groupby(l):
        group_list = list(group)
        if len(group_list) == 1:
            result.append(k)
    return result


def update_hours_cells(worksheet, cells, working_hours):
    cell_values = [cell.value for cell in cells if cell.value.strip()]
    sorted_hours = sorted(
        cell_values + working_hours, key=cmp_to_key(hours_comparator))
    unified_hours = remove_consecutive_duplicates(sorted_hours)
    for cell, hour in zip(cells, unified_hours):
        cell.value = hour
    worksheet.update_cells(cells, 'USER_ENTERED')


def update_description(project_config, worksheet, description_cell, new_description):
    value = ''
    user_config = get_user_config()
    is_strivelabs = project_config['timesheet'] == STRIVELABS_TIMESHEET
    duplicated = new_description in description_cell[2]
    if is_strivelabs and user_config["num_projects"] > 1 and not duplicated:
        value = f'({project_config["name"]}) {description_cell[2]} {new_description}'
    else:
        value = new_description
    worksheet.update_cell(description_cell[0], description_cell[1], value)


def update_timesheet(credentials, working_hours, description, project_config):
    timesheet = project_config['timesheet']
    with Halo(text=f'Writing on {timesheet}', spinner='dots') as spinner:
        try:
            gc = gspread.authorize(credentials)
            sheet = gc.open_by_url(timesheet) if is_url(timesheet) else gc.open(timesheet)
            worksheet = sheet.worksheet(project_config['timesheet_page'])
            hours_cells, description_cell = find_cells_to_write(worksheet)
            update_hours_cells(worksheet, hours_cells, working_hours)
            update_description(project_config, worksheet, description_cell, description)
            spinner.succeed(f'Writed on {timesheet}')
        except Exception as e:
            spinner.fail(str(e.args[1]))


def create_strivelabs_config(name):
    config = {
        'name': STRIVELABS_PROJECT_NAME,
        'timesheet': STRIVELABS_TIMESHEET,
        'timesheet_page': name
    }
    config_file = generate_project_config_filepath(STRIVELABS_PROJECT_NAME)
    with open(config_file, 'w') as json_file:
        json.dump(config, json_file)


def extract_data(content, project_config):
    try:
        preprocessed_lines = preprocess_file(content)
        date_format = project_config['date_format']
        daily_message = create_daily_message(preprocessed_lines, date_format)
        description = create_description_for_timesheet(preprocessed_lines)
        working_hours = parse_working_hours(preprocessed_lines[0])
        return (daily_message, working_hours, description)
    except ParsingError as e:
        print(e)
    except Exception:
        pass


@click.group()
def cli():
    pass


@cli.command()
def init():
    get_credentials()
    is_strivelabs = click.confirm('Do you belong to Strivelabs?')
    user_config = {'is_strivelabs': is_strivelabs}
    if is_strivelabs:
        name = click.prompt('Your name on Strivelabs timesheet')
        create_strivelabs_config(name)
    user_config['name'] = name
    user_config['num_projects'] = 0
    with open(USER_CONFIG_PATH, 'w') as json_file:
        json.dump(user_config, json_file)


@cli.command()
def create_project():
    user_config = get_user_config()
    name = click.prompt(
        'Project Name (will be used to identify this project)')
    timesheet = click.prompt('Timesheet name or url')
    timesheet_page = click.prompt(
        'Timesheet page name', default=user_config.get('name', ''))
    date_format = click.prompt(
        'Daily date format (empty for no date)', default='Today')
    print(SLACK_INFO_PROMPT)
    slack_token = click.prompt('Slack API token')
    daily_channel = click.prompt(
        'Slack channel name', default='#daily-scrum')
    config = {
        'name': name,
        'date_format': date_format,
        'slack_token': slack_token,
        'channel': daily_channel,
        'timesheet': timesheet,
        'timesheet_page': timesheet_page
    }
    config_file = generate_project_config_filepath(name)
    user_config['num_projects'] = user_config['num_projects'] + 1
    with open(config_file, 'w') as file:
        json.dump(config, file)
    with open(USER_CONFIG_PATH, 'w') as file:
        json.dump(user_config, file)


@cli.command()
@click.argument('project')
@click.option('--slack/--no-slack', default=True)
@click.option('--timesheet/--no-timesheet', default=True)
@click.option('--strivelabs/--no-strivelabs', default=True)
def write(project, slack, timesheet, strivelabs):
    user_config = get_user_config()
    project_config = get_project_config(project)
    if not project_config:
        print('\nProject not exists. Aborting...')
        return
    credentials = get_credentials()
    content = open_editor()
    if not content:
        print('\nAborted')
        return
    data = extract_data(content, project_config)
    if not data:
        print('Invalid format. Aborting...')
        return
    daily_message, working_hours, description = data
    total_working_hours = compute_total_hours(working_hours)
    print(f'Total working hours: {total_working_hours[0]}:{total_working_hours[1]}')
    if slack:
        post_message_on_slack(daily_message, project_config)
    if timesheet:
        update_timesheet(credentials, working_hours, description,
                         project_config)
        if user_config['is_strivelabs'] and strivelabs:
            strivelabs_config = get_strivelabs_project_config(project)
            update_timesheet(credentials, working_hours, description, strivelabs_config)

