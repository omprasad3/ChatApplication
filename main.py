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
            print(session)
            if "name" in session:
                return redirect(url_for('home'))
            elif request.method == "POST" and request.form.get("name"):
                session['name'] = request.form.get("name")
                return render_template('home.html', name = session["name"])
            else:
                return render_template('welcome.html')

        @self.app.route("/home", methods = ['GET', 'POST'])
        def home():
            #if request method is post
            if request.method == "POST":
                if request.form.get("reset") != None:
                    session.clear()
                    return redirect(url_for('welcome_screen'))
                code = request.form.get("code")
                join = request.form.get("join", False)
                create = request.form.get("create", False)
                
                if join != False and not code:
                    return render_template("home.html", error="Please enter a room code", name=session['name'])

                channel = code
                if create != False:
                    channel = self.generate_unique_code(4)
                    self.channels[channel] = {"members": 0, "messages": []}
                elif code not in self.channels:
                    return render_template("home.html", error="Room does not exist", name=session['name'])


                session["channel"] = channel 
                return redirect(url_for("channel"))

            return render_template("home.html", name=session['name'])


        @self.app.route("/channel")
        def channel():
            channel = session.get("channel")
            if channel is None or session.get("name") is None or channel not in self.channels:
                return redirect(url_for("home"))
            return render_template("channel.html", code=channel)


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

