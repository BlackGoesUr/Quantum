from flask import Flask
from threading import Thread
import os

app = Flask('')

@app.route('/')
def home():
    """Home route for status checks"""
    return "JoJo Bot is online!"

def run():
    """Run the web server"""
    app.run(host='0.0.0.0', port=8000)

def keep_alive():
    """Start the server in a separate thread"""
    t = Thread(target=run)
    t.daemon = True
    t.start()
