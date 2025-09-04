from flask import Flask, render_template, request, session, redirect, url_for
from flask_socketio import join_room, leave_room, send, SocketIO
import random
from string import ascii_uppercase


class MeetApp:
    def __init__(self):
        self.app = Flask(__name__)
        self.app.config["SECRET_KEY"] = "itsasecret"
        self.socketio = SocketIO(self.app)
        self.channels = {}
        self._configure_routes()


    def generate_unique_code(self, length):
        while True:
            code = ""
            for _ in range(length):
                code += random.choice(ascii_uppercase)

            if code not in self.channels:
                break

        return code

    def run(self):
        self.socketio.run(self.app, debug=True)

    def _configure_routes(self):
        #the welcome screen shows the welcome screen and takes in the name and sets it as the username
        #but if the username is already set then redirect the user to home screen
        @self.app.route("/", methods = ["GET", "POST"])
        def welcome_screen():
            #if the username is already set then redirect the user
            if request.method == "POST" and request.form.get("name"):
                session['name'] = request.form.get("name")
                return redirect(url_for('home'))
            name = "" if "name" not in session else session["name"]
            return render_template('welcome.html', name=name)

        @self.app.route("/home", methods = ['GET', 'POST'])
        def home():
            #if not the name is present redirect to the welcome screen
            if "name" not in session:
                return redirect(url_for('welcome_screen'))
            #if request method is post
            if request.method == "POST":
                join = request.form.get("join")
                create = request.form.get("create")
                if join:
                    return redirect(url_for('join'))
                if create:
                    return redirect(url_for('create'))

                session["channel"] = channel 
                return redirect(url_for("channel"))

            return render_template("home.html", name=session['name'])


        @self.app.route("/channel")
        def channel():
            #if not the name is present redirect to the welcome screen
            if "name" not in session:
                return redirect(url_for('welcome_screen'))
            channel = session.get("channel")
            if channel is None or session.get("name") is None or channel not in self.channels:
                return redirect(url_for("home"))
            return render_template("channel.html", code=channel)

        @self.app.route('/join')
        def join():
            #if not the name is present redirect to the welcome screen
            if "name" not in session:
                return redirect(url_for('welcome_screen'))
            #TODO:
            return render_template("join_channel.html")
            
        @self.app.route('/create')
        def create():
            #if not the name is present redirect to the welcome screen
            if "name" not in session:
                return redirect(url_for('welcome_screen'))
            #TODO:
            return render_template("create_channel.html")
 
           
        @self.socketio.on('message')
        def message(data):
            channel = session.get("channel")
            if channel not in self.channels:
                return

            content = {
                    "name": session.get("name"),
                    "message": data["data"]
            }
            send(content, to=channel)
            self.channels[channel]["messages"].append(content)
            print(f'{session.get("name")} said: {data["data"]}')

        @self.socketio.on('connect')
        def connect(auth):
            channel = session.get("channel")
            name = session.get("name")
            if not channel or not name:
                return
            if channel not in self.channels:
                leave_room(channel)
                return
            join_room(channel)
            send({"name": name, "message": "has entered the room"}, to=channel)
            self.channels[channel]["members"] += 1
            print(f"{name} joined room {channel}")


        @self.socketio.on("disconnect")
        def disconnect():
            channel = session.get("channel")
            name = session.get("name")
            leave_room(channel)

            if channel in self.channels:
                self.channels[channel]["members"] -= 1
                if self.channels[channel]["members"] <= 0:
                    del self.channels[channel]

            send({"name": name, "message": "has left the room"}, to=channel)
            print(f'{name} has left the room {channel}')

if __name__ == '__main__':
    app = MeetApp()
    app.run()

