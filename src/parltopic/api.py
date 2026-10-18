from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from parltopic.classification.service import ClassificationService
from parltopic.config import get_settings
from parltopic.models import Affair, ClassificationResult, TopicDefinition


@asynccontextmanager
async def lifespan(app: FastAPI):
    with ClassificationService(get_settings()) as service:
        app.state.classifier = service
        yield


app = FastAPI(title="ParlTopic API", version="0.1.0", lifespan=lifespan)


class ClassificationRequest(Affair):
    topic: TopicDefinition


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/classify", response_model=ClassificationResult)
def classify(request: ClassificationRequest, http_request: Request) -> ClassificationResult:
    topic = request.topic
    affair = Affair.model_validate(request.model_dump(exclude={"topic"}))
    return http_request.app.state.classifier.classify(affair, topic)

