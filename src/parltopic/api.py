from fastapi import FastAPI

from parltopic.classification.service import ClassificationService
from parltopic.config import get_settings
from parltopic.models import Affair, ClassificationResult, TopicDefinition

app = FastAPI(title="ParlTopic API", version="0.1.0")


class ClassificationRequest(Affair):
    topic: TopicDefinition


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/classify", response_model=ClassificationResult)
def classify(request: ClassificationRequest) -> ClassificationResult:
    topic = request.topic
    affair = Affair.model_validate(request.model_dump(exclude={"topic"}))
    return ClassificationService(get_settings()).classify(affair, topic)

