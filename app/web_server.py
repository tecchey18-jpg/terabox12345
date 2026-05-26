from flask import Flask
import os

app = Flask(__name__)

@app.route('/')
def health():
    return "🟢 TeraStreamBot is alive"

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
