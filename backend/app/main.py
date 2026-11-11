import json
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sklearn

from app.api.routes import router
from app.api.websocket import router as websocket_router
from app.config import CORS_ORIGINS, DEFAULT_CONFIG, MODEL_DIR
from app.database import Base, SessionLocal, engine
from app.ml.train import TRAINING_DATA_VERSION, train_models
from app.models import ConfigurationRecord, ModelTrainingRecord
from app.middleware import RequestSizeLimitMiddleware
from app.rate_limits import ensure_rate_limit_storage


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        ensure_rate_limit_storage(connection)
    with SessionLocal() as db:
        if db.get(ConfigurationRecord, 1) is None:
            db.add(ConfigurationRecord(id=1, values_json=json.dumps(DEFAULT_CONFIG)))
            db.commit()
        has_models = (MODEL_DIR / "solar.joblib").exists() and (MODEL_DIR / "demand.joblib").exists()
        latest_training = db.query(ModelTrainingRecord).order_by(ModelTrainingRecord.trained_at.desc()).first()
        stored_metrics = json.loads(latest_training.metrics_json) if latest_training else {}
        stored_metadata = stored_metrics.get("_metadata", {})
        stored_version = stored_metadata.get("scikit_learn_version")
        stored_data_version = stored_metadata.get("training_data_version")
        if (
            not has_models
            or stored_version != sklearn.__version__
            or stored_data_version != TRAINING_DATA_VERSION
        ):
            trained = train_models()
            db.add(
                ModelTrainingRecord(
                    metrics_json=json.dumps(
                        {
                            **trained["metrics"],
                            "_metadata": {
                                "scikit_learn_version": trained["model_version"],
                                "training_data_version": trained["training_data_version"],
                            },
                        }
                    ),
                    samples=trained["samples"],
                )
            )
            db.commit()
    yield


fastapi_app = FastAPI(
    title="EcoPulse Energy Management API",
    description="Local predictive neighborhood energy and abstract flywheel simulation. All values are simulated.",
    version="1.0.0",
    lifespan=lifespan,
)
fastapi_app.include_router(router)
fastapi_app.include_router(websocket_router)

# Wrap the complete FastAPI app so CORS headers are added to unhandled error responses too.
app = CORSMiddleware(
    app=RequestSizeLimitMiddleware(fastapi_app),
    allow_origins=list(CORS_ORIGINS),
    allow_credentials=False,
    allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@fastapi_app.get("/")
def root() -> dict:
    return {"name": "EcoPulse", "status": "running", "docs": "/docs", "simulated": True}
