from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class CreateUser(BaseModel):
    email: str
    password: str


@app.post("/register_user/")
def register_user(user: CreateUser):
    return {"message": "User registration request received", "mail": user.email}
