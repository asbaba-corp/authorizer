import json
import boto3
from botocore.exceptions import ClientError
from datetime import datetime
import bcrypt

print("Loading lambda function")
dynamo = boto3.client("dynamodb")


def respond(err, res=None):
    return {
        "statusCode": "400" if err else "200",
        "body": err.message if err else json.dumps(res),
        "headers": {
            "Content-Type": "application/json",
        },
    }


def check_existing_user(email):
    try:
        response = dynamo.get_item(
            TableName="Users",
            Key={"email": {"S": email}},
        )
        return "Item" in response
    except ClientError:
        return False


def register_user_in_db(user):
    try:
        response = dynamo.put_item(
            TableName="Users",
            Item={
                "email": {"S": user["email"]},
                "password": {"S": user["password"]},
                "created_at": {"S": user["created_at"]},
            },
        )
        return response
    except ClientError as exception:
        return {"error": exception.response["Error"]["Message"]}


def lambda_handler(event, context):
    try:
        payload = json.loads(event["body"])
        email = payload.get("email")
        password = payload.get("password")

        if email and check_existing_user(email):
            return respond(ValueError("Email already exists"))

        hashed_password = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        user = {
            "email": email,
            "password": hashed_password,
            "created_at": datetime.utcnow().isoformat(),
        }
        response = register_user_in_db(user)
        return respond(None, response)
    except Exception as e:
        return respond(ValueError(str(e)))
