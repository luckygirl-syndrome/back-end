from flask import Flask, jsonify
import requests

app = Flask(__name__)

# If running separately, we might configure the API URL here
API_BASE_URL = "http://localhost:8001" 

@app.route("/")
def index():
    return "<h1>Hello from Flask!</h1><p><a href='/users'>View Users</a></p>"

@app.route("/users")
def users_page():
    # Example to fetch data from the FastAPI service (if running)
    try:
        response = requests.get(f"{API_BASE_URL}/api/users")
        users = response.json()
        user_list = "".join([f"<li>{u['name']}</li>" for u in users])
        return f"<h1>User List</h1><ul>{user_list}</ul>"
    except Exception as e:
         return f"<h1>Error</h1><p>Could not fetch users from API: {e}</p>"

if __name__ == "__main__":
    app.run(port=5001, debug=True)
