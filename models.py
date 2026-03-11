from sqlalchemy import Column, Integer, String
from database import Base

class Song(Base):
    __tablename__ = "songs"

    id = Column(Integer, primary_key=True)
    title = Column(String)
    artist = Column(String)
    youtube_url = Column(String)
    status = Column(String, default="processing")
    output_dir = Column(String)