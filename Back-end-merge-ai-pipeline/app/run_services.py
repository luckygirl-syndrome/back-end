import subprocess
import sys
import time
import os

def run_services():
    # Get the current python executable
    python_executable = sys.executable
    
    # Paths to the service scripts
    # We need to run them as modules or scripts. 
    # Running as modules verify the path is correct
    project_root = os.path.dirname(os.path.abspath(__file__))
    
    # Env with python path
    env = os.environ.copy()
    env["PYTHONPATH"] = project_root

    print("Starting FastAPI server on port 8001...")
    # Run FastAPI using uvicorn directly via module
    fastapi_cmd = [python_executable, "-m", "uvicorn", "services.api_server:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]
    fastapi_process = subprocess.Popen(fastapi_cmd, cwd=project_root, env=env)

    print("Starting Flask server on port 5001...")
    # Run Flask
    flask_cmd = [python_executable, "services/web_server.py"]
    flask_process = subprocess.Popen(flask_cmd, cwd=project_root, env=env)

    try:
        while True:
            time.sleep(1)
            # Check if processes are still alive
            if fastapi_process.poll() is not None:
                print("FastAPI process exited unexpectedly.")
                flask_process.terminate()
                break
            if flask_process.poll() is not None:
                print("Flask process exited unexpectedly.")
                fastapi_process.terminate()
                break
    except KeyboardInterrupt:
        print("\nStopping services...")
        fastapi_process.terminate()
        flask_process.terminate()
        fastapi_process.wait()
        flask_process.wait()
        print("Services stopped.")

if __name__ == "__main__":
    run_services()
