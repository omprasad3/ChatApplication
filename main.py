from flask import Flask, render_template, request, session, redirect, url_for, g
from flask_socketio import join_room, leave_room,  SocketIO
from datetime import datetime
import random
import sqlite3
import os
from urllib.parse import urlparse
from string import hexdigits


class IRCApp:
    def __init__(self):
        self.app = Flask(__name__)
        self.DATABASE = "database.db"
        self.UPLOAD_FOLDER = 'uploads'
        os.makedirs(self.UPLOAD_FOLDER, exist_ok=True)
        self.app.config["SECRET_KEY"] = "itsasecret"
        self.socketio = SocketIO(self.app)
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

    #returns True if the user is not logged in or has no recored in db
    def check_session(self):
        #session check
        if 'user_id' not in session or 'username' not in session or session['user_id'] in [None, ''] or session['username'] in [None, '']:
            return True
        cursor = self.get_db().cursor()
        cursor.execute(f'SELECT * FROM user WHERE user_id = "{session['user_id']}" and username = "{session['username']}";')
        if len(cursor.fetchall()) == 0:
            return True
        return False

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
        #login page
        @self.app.route("/login", methods = ["GET", "POST"])
        def login():
            #redirect to welcome if username and user_id is already present
            if "username" in session and "user_id" in session:
                cursor = self.get_db().cursor()
                cursor.execute(f'SELECT * FROM user WHERE user_id = "{session['user_id']}" and username = "{session['username']}";')
                if len(cursor.fetchall()) != 0:
                    return redirect(url_for("welcome_screen"))
                session.pop("username", None)
                session.pop("user_id", None)


            if request.method == "POST" and request.form.get("action"):
                username = request.form.get("username")
                password = request.form.get("passwordInput") 
                action = request.form.get("action")
                #check for empty username or password
                if password in [None, ''] or username in [None, '']:
                    return render_template("login.html", error = 'Empty username or password')

                db = self.get_db()
                cursor = db.cursor()
                if action == "register":
                    #check if the username is already taken or not
                    query = f'SELECT * from user WHERE username = "{username}";'
                    cursor.execute(query)
                    row = cursor.fetchall()
                    #the username is taken
                    if len(row) != 0:
                        return render_template('login.html', error = f'Username "{username}" is already taken')
                        
                    #insert the new user in the database
                    user_id = self.generate_unique_code(10, 'user_id')
                    query = f'INSERT INTO user (user_id, username, password, channel_id, user_type) VALUES ("{user_id}", "{username}", "{password}", NULL, "NORMAL")';
                    cursor.execute(query)
                    db.commit()
                    #return redirect(url_for("welcome_screen"))
                    return render_template("login.html", username = username, success = "You have registered successfully, use your credentials to login")
                elif action == "login":
                    query = f'SELECT * from user WHERE username = "{username}" and password = "{password}";'
                    cursor.execute(query)
                    row = cursor.fetchall()

                    #the user is present
                    if len(row) != 0:
                        #set the session varaibles
                        session['user_id'] = row[0][0]
                        session['username'] = row[0][1]
                        session['channel_id'] = row[0][2]
                        #if the channel_id is present then redirect to that channel 
                        if session['channel_id'] != None: return redirect(url_for("channel"))
                        # or redirect to the welcome screen to join or create a channel
                        return redirect(url_for("welcome_screen"))
                    #return the user for entering wrong password
                    return render_template('login.html', username=username, error = 'Username or Password is INCORRECT')
                else:
                    print("Some abnormal submit action has got from login page:", action)
                    return render_template('login.html', username=username)
            #normal rendering of login page
            return render_template('login.html')


        @self.app.route("/delete_channel")
        def delete_channel():
            if not self.check_session() and "channel_id" in session and urlparse(request.referrer).path == "/channel":
                db = self.get_db()
                cursor = db.cursor()
                cursor.executescript(f'UPDATE user SET channel_id = NULL, user_type = "NORMAL" WHERE channel_id = "{session['channel_id']}";DELETE FROM channel WHERE channel_id = "{session['channel_id']}";DELETE FROM message WHERE channel_id = "{session['channel_id']}";')
                db.commit()
                self.socketio.emit("exit_all", {"channel_id": session['channel_id']}, to=session['channel_id'])
                session.pop('channel_id', None)
            return redirect(url_for('welcome_screen', info = "Channel deleted successfully"))


        #change channel name, description, password
        @self.app.route("/update_channel", methods = ["GET", "POST"])
        def update_channel():
            if not self.check_session() and "channel_id" in session and request.form.get('action') == 'updateChannel' and urlparse(request.referrer).path == "/channel":
                channel_name = request.form.get('channelNameOfModal') 
                channel_password = request.form.get('passwordInput') 
                channel_description = request.form.get('channelDescription') 
                if channel_name not in ['', None] and channel_password not in ['', None]:
                    query = f'UPDATE channel SET channel_name = "{channel_name}", password = "{channel_password}", channel_description = "{channel_description}" WHERE channel_id = "{session['channel_id']}";'
                    self.get_db().execute(query)
                    self.get_db().commit()
                    self.socketio.emit("new_message", {"content": f"Channel details are updated by {session['username']} [ {session['user_id']} ]", "message_type": "broadcast"}, to=session['channel_id'])

            return redirect(url_for("channel"))

        @self.app.route("/update_user", methods = ["GET", "POST"])
        def update_user():
            if not self.check_session() and request.method == "POST" and request.form.get('action') == 'updateUser' and urlparse(request.referrer).path == "/":
                username = request.form.get('usernameOfModal') 
                user_password = request.form.get('passwordInput') 
                if username not in ['', None] and user_password not in ['', None]:
                    cursor = self.get_db().cursor()
                    #check if the username is already taken
                    cursor.execute(f'SELECT * FROM user WHERE username = "{username}";')
                    if len(cursor.fetchall()) != 0:
                        return redirect(url_for("welcome_screen", error = f"Username '{username}' is already taken, try with a different username"))
                    query = f'UPDATE user SET username = "{username}", password = "{user_password}" WHERE user_id = "{session['user_id']}";'
                    self.get_db().execute(query)
                    self.get_db().commit()
                    session['username'] = username

            return redirect(url_for('welcome_screen'))

        @self.app.route("/leave_channel")
        def leave_channel():
            if not self.check_session() and "channel_id" in session and urlparse(request.referrer).path == "/channel":
                self.get_db().executescript(f'UPDATE user SET channel_id = NULL, user_type = "NORMAL" WHERE user_id = "{session['user_id']}" and username = "{session['username']}";')
                self.get_db().commit()
                self.socketio.emit("new_message", {"message_type": "broadcast", "content": f"{session['username']} [ {session['user_id']} ] has left the channel"}, to=session['channel_id'])
                session.pop('channel_id', None)

            return redirect(url_for('login'))



        @self.app.route("/delete_user")
        def delete_user():
            if not self.check_session() and urlparse(request.referrer).path == "/":
                #delete the user from the database and remove the session variables and redirect to login page
                db = self.get_db()
                cursor = db.cursor()
                cursor.execute(f'SELECT * FROM user WHERE user_id = "{session['user_id']}" and username = "{session['username']}";')
                row = cursor.fetchall()

                if len(row) != 0:
                    cursor.execute(f'DELETE FROM user WHERE user_id = "{session['user_id']}" and username = "{session["username"]}";')
                    db.commit()
                else:
                    return redirect(url_for("welcome_screen", error = f"Invalid User, Login required"))

                cursor.execute(f'SELECT * FROM channel WHERE owner_id = "{session['user_id']}";')
                row = cursor.fetchall()
                for channel in row:
                    self.socketio.emit("exit_all", None, to=channel[0])
                    cursor.executescript(f'DELETE FROM channel WHERE channel_id = "{channel[0]}";UPDATE user SET channel_id = NULL WHERE channel_id = "{channel[0]}";DELETE FROM message WHERE channel_id = "{channel[0]}";')
                    db.commit()
                session.pop('user_id', None)
                session.pop('username', None)
                session.pop('channel_id', None)
                return redirect(url_for("login"))
            return redirect(request.referrer or url_for('welcome_screen'))

        
        @self.app.route("/logout")
        def logout():
            if not self.check_session() and urlparse(request.referrer).path == "/":
                if 'channel_id' in session:
                    self.get_db().executescript(f'UPDATE user SET channel_id = NULL, user_type = "NORMAL" WHERE user_id = "{session['user_id']}" and username = "{session['username']}";')
                    self.get_db().commit()
                session.pop('channel_id', None)
                session.pop('user_id', None)
                session.pop('username', None)

            return redirect(url_for('login'))
           

        #the welcome screen shows the welcome screen and takes in the name and sets it as the username
        #but if the username is already set then redirect the user to home screen
        @self.app.route("/", methods = ["GET", "POST"])
        def welcome_screen():
            if self.check_session():
                return redirect(url_for("login"))

            if request.method == "POST":
                db = self.get_db()
                cursor = db.cursor()
               
                #check if the post action was of join or create and redirect accordingly
                type_of_action = request.form.get("action")
                match type_of_action:
                    case "join":
                        return redirect(url_for("join"))
                    case "create":
                        return redirect(url_for("create"))
                    case '_':
                        print("An unknown post request is got via welcome post")
            if request.args.get("error"):
                return render_template('welcome.html', username=session['username'], error = request.args.get('error'))
            if request.args.get("info"):
                return render_template('welcome.html', username=session['username'], info = request.args.get('info'))
            return render_template('welcome.html', username=session['username'])

        @self.app.route("/channel")
        def channel():
            if self.check_session():
                return redirect(url_for("login"))

            db = self.get_db()
            cursor = db.cursor()
            cursor.execute(f'SELECT * FROM channel WHERE channel_id = "{session['channel_id']}";')
            row = cursor.fetchall()
            
            if len(row) == 0:
                print(f"No such channel: {session['channel_id']}")
                return redirect(url_for("welcome_screen"))

            cursor.execute(f'SELECT user.username, sender_id, content, timestamp FROM message JOIN user ON user.user_id = message.sender_id WHERE message.channel_id = "{session['channel_id']}" ORDER BY timestamp ASC;')
            messages = cursor.fetchall()
            return render_template("channel.html", code=session['channel_id'], messages=messages,owner_id=row[0][4], channel_name=row[0][1], channel_description=row[0][2], user_id=session['user_id'])


        @self.app.route('/join', methods = ['GET', 'POST'])
        def join():
            if self.check_session():
                return redirect(url_for("login"))

            cursor = self.get_db().cursor()
            cursor.execute(f'SELECT * FROM user WHERE user_id = "{session['user_id']}";')
            rows = cursor.fetchall()
            
            #if user already has a channel id
            if rows[0][2] != None:
                session['channel_id'] = rows[0][2]
                return redirect(url_for('channel'))

            if request.method == "POST":
                channel_id = request.form.get("channel-ID", False)
                #if channel_id is not null
                if channel_id:
                    cursor.execute(f'SELECT * FROM channel WHERE channel_id = "{channel_id}" and password = "{request.form.get("passwordInput")}";')
                    rows = cursor.fetchall()
                    #check if the channel is present or not
                    if len(rows) != 1:
                        return render_template("join_channel.html", error=f"No such Channel or Password is incorrect", channel_id = channel_id, username=session['username'])

                    #see if the user is owner of the channel then update it's user_type and channel_id
                    user_type = 'OWNER' if rows[0][4] == session['user_id'] else 'NORMAL'

                    query = f'UPDATE user SET user_type = "{user_type}", channel_id = "{channel_id}" WHERE user_id = "{session['user_id']}";'
                    self.get_db().executescript(query)
                    self.get_db().commit()

                    #set the channel_id for the user and redirect to channel page
                    session["channel_id"] = channel_id
                    self.socketio.emit("new_message", {"message_type": "broadcast", "content": f"{session['username']} [ {session['user_id']} ] has joined the channel"}, to=session['channel_id'])
                    return redirect(url_for("channel"))
            return render_template("join_channel.html", username=session["username"])
            
        @self.app.route('/create', methods = ['GET', 'POST'])
        def create():
            if self.check_session():
                return redirect(url_for("login"))

            cursor = self.get_db().cursor()
            cursor.execute(f'SELECT * FROM user WHERE user_id = "{session['user_id']}";')
            rows = cursor.fetchall()
            
            #if user already has a channel id
            if rows[0][2] != None:
                session['channel_id'] = rows[0][2]
                return redirect(url_for('channel'))

            if request.method == "POST":
                action = request.form.get("action", False)
                if action == "create":
                    #get channel id, channel name, password and description as provided
                    channel_id = self.generate_unique_code(5, "channel_id");
                    channel_password = request.form.get("passwordInput")
                    channel_name = request.form.get("channel-name")
                    channel_description = request.form.get("channel-description")

                    #return to the page with an error if there is no password provided
                    if request.form.get("passwordInput") in ["",None]:
                        return render_template("create_channel.html", error="Password is NOT provided")

                    #check if the id is repeated
                    #db =  self.get_db()
                    #cursor= db.cursor()
                    #cursor.execute(f'SELECT * FROM channel WHERE channel_id = "{channel_id}";')
                    #if len(cursor.fetchall()) > 0:
                    #    return render_template("create_channel.html", channel_id=channel_id, channel_name=channel_name, channel_description=channel_description, username=session['username'],error=f"A Channel with the ID: {channel_id} already exists")

                    db =  self.get_db()
                    #query for inserting the channel details in the channel table and updating user details
                    query = f'INSERT INTO channel ( channel_id, channel_name, channel_description, password, owner_id ) VALUES ("{channel_id}", "{channel_name}", "{channel_description}", "{channel_password}", "{session['user_id']}");'
                    db.execute(query)
                    db.commit()
                    
                    return render_template("create_channel.html", username=session["username"], success = f"Channel ID of newly created channel is: '{channel_id}' - SAVE THIS CODE TO ACCESS THE CHANNEL")

            return render_template("create_channel.html", username=session["username"])
 
           
        #TODO: work from here
        @self.socketio.on('send_message')
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
                    "username": username,
                    "user_id": session['user_id'],
                    "content": data["data"],
                    "timestamp" : current_time
            }
            self.socketio.emit("new_message", content, to=channel_id)
            query = f'INSERT INTO message (sender_id, channel_id, content, timestamp) VALUES ("{session['user_id']}", "{channel_id}", "{data['data']}", "{current_time}");'
            cursor.execute(query)
            db.commit()
            print(f'{username} said: {data["data"]}')

        @self.socketio.on('connect')
        def connect(auth):
            channel_id = session["channel_id"]
            username = session["username"]
            user_id = session["user_id"]
            if not channel_id or not username or not user_id:
                return
            cursor = self.get_db().cursor()
            cursor.execute(f'SELECT * FROM channel WHERE channel_id = "{channel_id}";')

            if len(cursor.fetchall()) != 1:
                leave_room(channel_id)
                return
            join_room(channel_id)


        @self.socketio.on("disconnect")
        def disconnect():
            channel_id = session['channel_id']
            leave_room(channel_id)

if __name__ == '__main__':
    app = IRCApp()
    app.run()
