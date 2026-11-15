from fastapi import Depends
from sqlalchemy.orm import Session

from app.database.base import get_db
from app.services.conversation import ConversationService


def get_conversation_service(db: Session = Depends(get_db)) -> ConversationService:
    return ConversationService(db)
