import sqlite3


class Database:
    def __init__(self, db_name='poem.db'):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS poem (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                user_id INTEGER NOT NULL,
                                line TEXT NOT NULL,
                                photo BLOB NOT NULL
                            )''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS sent_poem (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                user_id INTEGER NOT NULL,
                                line TEXT NOT NULL
                            )''')
        self.conn.commit()

    def user_exists(self, user_id):
        self.cursor.execute('SELECT 1 FROM poem WHERE user_id = ?', (user_id,))
        return self.cursor.fetchone() is not None

    def get_next_line(self, user_id):
        self.cursor.execute('SELECT COUNT(*) FROM sent_poem WHERE user_id = ?', (user_id,))
        sent_lines_count = self.cursor.fetchone()[0]

        self.cursor.execute('SELECT id, line, photo FROM poem WHERE user_id = ? ORDER BY id LIMIT 1 OFFSET ?',
                            (user_id, sent_lines_count))
        result = self.cursor.fetchone()

        if result:
            line_id, line, photo = result
            return line_id, line, photo
        return None

    def save_sent_line(self, user_id, line):
        self.cursor.execute('INSERT INTO sent_poem (user_id, line) VALUES (?, ?)', (user_id, line))
        self.conn.commit()

    def get_full_poem(self, user_id):
        self.cursor.execute('SELECT line FROM sent_poem WHERE user_id = ?', (user_id,))
        lines = self.cursor.fetchall()
        return '\n'.join([line[0] for line in lines])

    def fill_database_for_user(self, user_id, lines, photo_paths):
        # Remove existing lines for the user if needed
        self.cursor.execute('DELETE FROM poem WHERE user_id = ?', (user_id,))

        for idx, (line, photo_path) in enumerate(zip(lines, photo_paths)):
            with open(photo_path, 'rb') as f:
                photo = f.read()
            self.cursor.execute('INSERT INTO poem (user_id, line, photo) VALUES (?, ?, ?)', (user_id, line, photo))
        self.conn.commit()








