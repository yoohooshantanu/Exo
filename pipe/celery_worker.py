import os
import sys
from pathlib import Path
from celery import Celery
from dotenv import load_dotenv

# Ensure we can import from modules/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "modules"))

load_dotenv(PROJECT_ROOT / ".env")

broker_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

app = Celery("exo_tasks", broker=broker_url, backend=broker_url)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_concurrency=2, # Limit concurrency since retrievals are CPU heavy
)

@app.task(name="run_platon_retrieval_task", bind=True)
def run_platon_retrieval_task(self, planet_id: str, spec_id: str, retrieval_id: str):
    from platon_retrieval import run_platon_retrieval
    # We pass the retrieval_id so the DB can be updated properly
    run_platon_retrieval(planet_id, spec_id, retrieval_id)
    return {"status": "success", "retrieval_id": retrieval_id}

@app.task(name="run_biosignature_detection_task", bind=True)
def run_biosignature_detection_task(self, planet_name: str = None):
    from biosignature_detector import run as biosig_run
    # if planet_name is None, it runs for all
    biosig_run(target_planet=planet_name)
    return {"status": "success", "planet": planet_name or "all"}

@app.task(name="run_anomaly_sweep_task", bind=True)
def run_anomaly_sweep_task(self):
    from anomaly_detector import run as anomaly_run
    anomaly_run()
    return {"status": "success"}
