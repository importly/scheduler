# profile_list_tasks.py
import cProfile
import pstats

from fastapi.testclient import TestClient
from src.main import app

def profile_list_tasks():
    client = TestClient(app)

    profiler = cProfile.Profile()
    profiler.enable()

    # make a single call to your endpoint
    resp = client.get("/tasks/?skip=0&limit=100")
    print("Status code:", resp.status_code)
    _ = resp.json()   # force full serialization

    profiler.disable()
    profiler.dump_stats("list_tasks.prof")
    print("👉 Profile data written to list_tasks.prof")

    # Optional: print top 20 slowest funcs to stdout
    ps = pstats.Stats(profiler).sort_stats("cumtime")
    ps.print_stats(20)

if __name__ == "__main__":
    profile_list_tasks()
