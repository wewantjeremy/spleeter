from flask import Flask
from database import engine
from models import Base
from routes import bp


app = Flask(__name__)

Base.metadata.create_all(bind=engine)
app.register_blueprint(bp)
@app.route("/health")
def health():
    return "ok"


