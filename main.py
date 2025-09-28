from datetime import datetime
from flask import Flask, render_template, request, session, redirect, url_for, g
from flask_socketio import join_room, leave_room, send, SocketIO
import random
import sqlite3
from string import hexdigits


class IRCApp:
    def __init__(self):
        self.app = Flask(__name__)
        self.DATABASE = "database.db"
        self.app.config["SECRET_KEY"] = "itsasecret"
        self.socketio = SocketIO(self.app)
        self.channels = {}
        self._configure_routes()
        with self.app.app_context():
            self.init_db()

    def get_db(self):
            if "db" not in g:
                g.db = sqlite3.connect(self.DATABASE)
                g.db.row_factory = sqlite3.Row
                g.db.execute("PRAGMA foreign_keys = ON")
            return g.db

    def close_db(self):
            db = g.pop("db", None)
            if db is not None:
                db.close()

    def init_db(self):
            db = self.get_db()
            with open("schema.sql", "r") as f:
                db.executescript(f.read())
            db.commit()

    def generate_unique_code(self, length, type):
        while True:
            code = ''
            #generate the random code first
            for _ in range(length):
                code += random.choice(hexdigits)
            #match the type of the code
            match type:
                #for user code
                case 'user_id':
                    query = f'SELECT * FROM user where user_id = "{code}";'
                #for channel code
                case 'channel_id':
                    query = f'SELECT * FROM channel where channel_id = "{code}";'
                case _:
                    print("Unknown type of code has been asked for, the type is:", type)
                    return None
            #get the database's cursor
            cursor = self.get_db().cursor()
            cursor.execute(query)
            #break and go out only if the random code is unique
            if len(cursor.fetchall()) == 0:
                break
        return code

    def run(self):
        self.socketio.run(self.app, debug=True)

    def _configure_routes(self):
        #the welcome screen shows the welcome screen and takes in the name and sets it as the username
        #but if the username is already set then redirect the user to home screen
        @self.app.route("/", methods = ["GET", "POST"])
        def welcome_screen():
            #the below condition block checks, if a name is present and then after setting name, it redirects userto join or create page
            if request.method == "POST" and request.form.get("name"):
                session['username'] = request.form.get("name")
                db = self.get_db()
                cursor = db.cursor()
                #setting the user_id if not already there, that means the user is new 'maybe'
                if not "user_id" in session:
                    session["user_id"] = self.generate_unique_code(10, 'user_id')
                    query = f'INSERT into user (user_id, username, user_type) values ("{session["user_id"]}","{session["username"]}","NORMAL");'
                else:
                    #query = f"""INSERT INTO user (user_id, username, user_type) VALUES ("{session["user_id"]}", "{session["username"]}", "NORMAL") ON DUPLICATE KEY UPDATE username= "{session['username']}";"""
                    query = f'UPDATE user SET username = "{session["username"]}" WHERE user_id = "{session["user_id"]}";'
                cursor.execute(query)
                db.commit()
                
                #check if the post action was of join or create and redirect accordingly
                type_of_action = request.form.get("action")
                if type_of_action == "join":
                    return redirect(url_for("join"))
                elif type_of_action == "create":
                    return redirect(url_for("create"))
                else:
                    print("An unknown post request is got via welcome post")

            username = "" if "username" not in session else session["username"]
            return render_template('welcome.html', username=username)

        @self.app.route("/channel")
        def channel():
            #if not the name is present redirect to the welcome screen
            print("channel method is reachable")
            if "username" not in session:
                return redirect(url_for('welcome_screen'))

            db = self.get_db()
            cursor = db.cursor()
            query = f'SELECT channel_id FROM user WHERE user_id = "{session['user_id']}";'
            cursor.execute(query)
            rows = cursor.fetchall()
            if len(rows) != 1:
                print(f'Number of rows not equal to 1, found to be {len(rows)} in channel method, exited')
                return redirect(url_for('welcome_screen'))

            channel_id = rows[0][0]
            """ -> disabling the below two lines enable if something goes wrong
            if channel_id is None or session.get("channel_name") is None or channel not in self.channels:
                return redirect(url_for("home"))
            """
            #TODO: was retrieving the username and others, sending them to channel and making it show every message in the channel, which is there and also add after that a mechanism to show current messages too concurrently
            cursor.execute("SELECT user.username, message.content, message.timestamp FROM message INNER JOIN user ON messsage.sender_id = user.user_id ORDER BY message.timestamp ASC;")
            messages = cursor.fetchall()
            return render_template("channel.html", code=channel_id, messages = messages)

        @self.app.route('/join', methods = ['GET', 'POST'])
        def join():
            #if not the name is present redirect to the welcome screen
            if "username" not in session:
                return redirect(url_for('welcome_screen'))
            channel_id = request.form.get("channel-ID", False)
            #if channel_id is not null
            if channel_id:
                cursor = self.get_db().cursor()
                cursor.execute(f'SELECT * FROM channel WHERE channel_id = "{channel_id}";')
                rows = cursor.fetchall()
                #check if the channel is present or not
                if len(rows) == 0:
                    return render_template("join_channel.html", error=f"Channel {channel_id} does not exists", channel_id = channel_id)
                #if more than one channel of same id exists
                if len(rows) != 1:
                    return render_template("join_channel.html", error=f"More than one channel of '{channel_id}' exists, how?", channel_id = channel_id)
                #now if the channel is there, compare password 
                if rows[0][3] == request.form.get("passwordInput"):
                    return redirect(url_for("channel"))
                else:
                    return render_template("join_channel.html", error = "Wrong password entered", channel_id = channel_id)
                
            
            return render_template("join_channel.html", username=session["username"])
            
        @self.app.route('/create', methods = ['GET', 'POST'])
        def create():
            #if not the name is present redirect to the welcome screen
            if "username" not in session:
                return redirect(url_for('welcome_screen'))
            action = request.form.get("action", False)
            if action == "create":
                #make a channel id, get the name, password and description as provided
                channel_id = self.generate_unique_code(5, 'channel_id')
                channel_password = request.form.get("passwordInput")
                channel_name = request.form.get("channel-name")
                channel_description = request.form.get("channel-description")

                #return to the page with an error if there is no password provided
                if request.form.get("passwordInput") in ["",None]:
                    return render_template("create_channel.html", error="No password is provided")

                #query for inserting the channel details in the channel table
                query = f'INSERT INTO channel ( channel_id, channel_name, channel_description, password ) VALUES ("{channel_id}", "{channel_name}", "{channel_description}", "{channel_password}");'
                #appending query for inserting the user details in the user table
                query += f'UPDATE user SET user_type = "OWNER", channel_id = "{channel_id}" WHERE user_id = "{session["user_id"]}";'
                db =  self.get_db()
                db.executescript(query)
                db.commit()

                #redirect to the channel
                return redirect(url_for('channel'))
            return render_template("create_channel.html", username=session["username"])
 
           
        @self.socketio.on('message')
        def message(data):
            db = self.get_db()
            cursor = db.cursor()
            query = f'SELECT channel_id FROM user WHERE user_id = "{session['user_id']}";'
            cursor.execute(query)
            rows = cursor.fetchall()
            #check if there is more than one row, if yes throw error
            if len(rows) != 1:
                print('more than 1 record for a single user_id found, exited')
                return 
            channel_id = rows[0][0]
            username = session['username']

            cursor.execute('SELECT channel_id FROM channel;')
            ids = [row[0] for row in cursor.fetchall()]
            #if not channel exists then return
            if channel_id not in ids:
                return

            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            content = {
                    "name": username,
                    "message": data["data"],
                    "timestamp" : current_time
            }
            send(content, to=channel_id)
            query = f'INSERT INTO message (sender_id, channel_id, content, timestamp) VALUES ("{session['user_id']}", "{channel_id}", "{data['data']}", "{current_time}");'
            cursor.execute(query)
            db.commit()
            print(f'{username} said: {data["data"]}')

        @self.socketio.on('connect')
        def connect(auth):
            db = self.get_db()
            cursor = db.cursor()
            query = f'SELECT * FROM user WHERE user_id = "{session['user_id']}";'
            cursor.execute(query)
            rows = cursor.fetchall()
            #check if there is more than one row, if yes throw error
            if len(rows) != 1:
                print('the returned rows of the query in "connect" found out not to be 1, exited')
                return None
            channel_id = rows[0]['channel_id']
            username = rows[0]['username']

            #check if channel_id, username is present and channel_id is of a valid  channel
            if not channel_id or not username:
                return
            query = f'SELECT * FROM channel WHERE channel_id = "{channel_id}";'
            cursor.execute(query)
            rows = cursor.fetchall()
            if len(rows) < 1:
                leave_room(channel_id)
                return
            elif len(rows) > 1:
                print(channel_id, " giving more than one channel rows")
                return

            join_room(channel_id)
            send({"name": username, "message": "has entered the room"}, to=channel_id)
            print(f"{username} joined room {channel_id}")


        @self.socketio.on("disconnect")
        def disconnect():
            db = self.get_db()
            cursor = db.cursor()
            query = f'SELECT * FROM user WHERE user_id = "{session['user_id']}";'
            cursor.execute(query)
            rows = cursor.fetchall()
            #check if there is more than one row, if yes throw error
            if len(rows) != 1:
                print('the returned rows of the query in "disconnect" found not to be 1, control exited')
                return
            channel_id = rows[0]['channel_id']
            username = rows[0]['username']
            leave_room(channel_id)

            #send the message to the channels that user has left the channel
            send({"name": username, "message": "has left the room"}, to=channel_id)
            print(f'{username} has left the room {channel_id}')

            #remove the user from the db
            query = f'DELETE FROM user WHERE user_id = "{session["user_id"]}";'
            db.execute(query)
            db.commit()
            session.clear()

if __name__ == '__main__':
    app = IRCApp()
    app.run()
