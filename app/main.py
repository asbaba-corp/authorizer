import re
import json
import boto3
from botocore.exceptions import ClientError
from jose import jwt, JWTError

print("Loading lambda function")
dynamo = boto3.client("dynamodb")

SECRET_KEY = "your-secret-key"
ALGORITHM = "HS256"


def respond(err, res=None):
    return {
        "statusCode": "400" if err else "200",
        "body": err.message if err else json.dumps(res),
        "headers": {
            "Content-Type": "application/json",
        },
    }


def get_current_user(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")  # type: ignore
        if email is None:
            raise Exception("Unauthorized")
        return email
    except JWTError:
        raise Exception("Invalid Token")


def get_user(email: str):
    try:
        query = f"SELECT * FROM Users WHERE email = '{email}'"
        response = dynamo.execute_statement(
            Statement=query,
        )

        if not response["Items"]:
            raise Exception(f"User with email '{email}' not found")
        user = response["Items"][0]
        user_data = {
            "id": user["id"]["S"],
            "email": user["email"]["S"],
            "password": user["password"]["S"],
            "created_at": user["created_at"]["S"],
        }
        return user_data
    except ClientError as exception:
        raise Exception(
            f"Database error: {exception.response['Error']['Message']}"
        ) from exception


def handler(event, context):
    try:
        # print("Method ARN: " + event["methodArn"])
        token = event["headers"]["authorization"]
    except KeyError as exception:
        return {
            "isAuthorized": "false",
            "context": {
                "stringKey": "Invalid token",
            },
        }

    """
    Validate the incoming token and user:
    """
    email = get_current_user(token)
    user = get_user(email)
    if not user:
        return {
            "isAuthorized": "false",
            "context": {
                "stringKey": "User not found",
            },
        }
    return {
        "isAuthorized": "true",
        "context": {
            "stringKey": "Invalid token",
        },
    }

    # If the token is valid, a policy must be generated which will allow or deny
    # If access is allowed, API Gateway will proceed with

    """This function must generate a policy that is associated with the recognized
    principal user identifier. Depending on your use case, you might store
    policies in a DB, or generate them on the fly.

    Keep in mind, the policy is cached for 5 minutes by default (TTL is
    configurable in the authorizer) and will apply to subsequent calls to any
    method/resource in the RestApi made with the same token.

    The example policy below denies access to all resources in the RestApi.
    """
    tmp = event["methodArn"].split(":")
    apiGatewayArnTmp = tmp[5].split("/")
    awsAccountId = tmp[4]

    policy = AuthPolicy(principalId, awsAccountId)
    policy.restApiId = apiGatewayArnTmp[0]
    policy.region = tmp[3]
    policy.stage = apiGatewayArnTmp[1]
    policy.denyAllMethods()
    # policy.allowMethod(HttpVerb.GET, '/pets/*')

    # Finally, build the policy
    authResponse = policy.build()

    context = {
        "key": "value",  # $context.authorizer.key -> value
        "number": 1,
        "bool": True,
    }
    authResponse["context"] = context

    return authResponse


class HttpVerb:
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    HEAD = "HEAD"
    DELETE = "DELETE"
    OPTIONS = "OPTIONS"
    ALL = "*"


class AuthPolicy(object):
    # The AWS account id the policy will be generated for. This is used to create the method ARNs.
    awsAccountId = ""
    # The principal used for the policy, this should be a unique identifier for the end user.
    principalId = ""
    # The policy version used for the evaluation. This should always be '2012-10-17'
    version = "2012-10-17"
    # The regular expression used to validate resource paths for the policy
    pathRegex = "^[/.a-zA-Z0-9-\*]+$"

    """Internal lists of allowed and denied methods.

    These are lists of objects and each object has 2 properties: A resource
    ARN and a nullable conditions statement. The build method processes these
    lists and generates the approriate statements for the final policy.
    """
    allowMethods = []
    denyMethods = []

    """Replace the placeholder value with a default API Gateway API id to be used in the policy.
    Beware of using '*' since it will not simply mean any API Gateway API id, because stars will greedily expand over '/' or other separators.
    See https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_resource.html for more details."""
    restApiId = "<<restApiId>>"

    """Replace the placeholder value with a default region to be used in the policy.
    Beware of using '*' since it will not simply mean any region, because stars will greedily expand over '/' or other separators.
    See https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_resource.html for more details."""
    region = "<<region>>"

    """Replace the placeholder value with a default stage to be used in the policy.
    Beware of using '*' since it will not simply mean any stage, because stars will greedily expand over '/' or other separators.
    See https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_resource.html for more details."""
    stage = "<<stage>>"

    def __init__(self, principal, awsAccountId):
        self.awsAccountId = awsAccountId
        self.principalId = principal
        self.allowMethods = []
        self.denyMethods = []

    def _addMethod(self, effect, verb, resource, conditions):
        """Adds a method to the internal lists of allowed or denied methods. Each object in
        the internal list contains a resource ARN and a condition statement. The condition
        statement can be null."""
        if verb != "*" and not hasattr(HttpVerb, verb):
            raise NameError(
                "Invalid HTTP verb " + verb + ". Allowed verbs in HttpVerb class"
            )
        resourcePattern = re.compile(self.pathRegex)
        if not resourcePattern.match(resource):
            raise NameError(
                "Invalid resource path: "
                + resource
                + ". Path should match "
                + self.pathRegex
            )

        if resource[:1] == "/":
            resource = resource[1:]

        resourceArn = "arn:aws:execute-api:{}:{}:{}/{}/{}/{}".format(
            self.region, self.awsAccountId, self.restApiId, self.stage, verb, resource
        )

        if effect.lower() == "allow":
            self.allowMethods.append(
                {"resourceArn": resourceArn, "conditions": conditions}
            )
        elif effect.lower() == "deny":
            self.denyMethods.append(
                {"resourceArn": resourceArn, "conditions": conditions}
            )

    def _getEmptyStatement(self, effect):
        """Returns an empty statement object prepopulated with the correct action and the
        desired effect."""
        statement = {
            "Action": "execute-api:Invoke",
            "Effect": effect[:1].upper() + effect[1:].lower(),
            "Resource": [],
        }

        return statement

    def _getStatementForEffect(self, effect, methods):
        """This function loops over an array of objects containing a resourceArn and
        conditions statement and generates the array of statements for the policy."""
        statements = []

        if len(methods) > 0:
            statement = self._getEmptyStatement(effect)

            for curMethod in methods:
                if curMethod["conditions"] is None or len(curMethod["conditions"]) == 0:
                    statement["Resource"].append(curMethod["resourceArn"])
                else:
                    conditionalStatement = self._getEmptyStatement(effect)
                    conditionalStatement["Resource"].append(curMethod["resourceArn"])
                    conditionalStatement["Condition"] = curMethod["conditions"]
                    statements.append(conditionalStatement)

            if statement["Resource"]:
                statements.append(statement)

        return statements

    def allowAllMethods(self):
        """Adds a '*' allow to the policy to authorize access to all methods of an API"""
        self._addMethod("Allow", HttpVerb.ALL, "*", [])

    def denyAllMethods(self):
        """Adds a '*' allow to the policy to deny access to all methods of an API"""
        self._addMethod("Deny", HttpVerb.ALL, "*", [])

    def allowMethod(self, verb, resource):
        """Adds an API Gateway method (Http verb + Resource path) to the list of allowed
        methods for the policy"""
        self._addMethod("Allow", verb, resource, [])

    def denyMethod(self, verb, resource):
        """Adds an API Gateway method (Http verb + Resource path) to the list of denied
        methods for the policy"""
        self._addMethod("Deny", verb, resource, [])

    def allowMethodWithConditions(self, verb, resource, conditions):
        """Adds an API Gateway method (Http verb + Resource path) to the list of allowed
        methods and includes a condition for the policy statement. More on AWS policy
        conditions here: http://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements.html#Condition
        """
        self._addMethod("Allow", verb, resource, conditions)

    def denyMethodWithConditions(self, verb, resource, conditions):
        """Adds an API Gateway method (Http verb + Resource path) to the list of denied
        methods and includes a condition for the policy statement. More on AWS policy
        conditions here: http://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements.html#Condition
        """
        self._addMethod("Deny", verb, resource, conditions)

    def build(self):
        """Generates the policy document based on the internal lists of allowed and denied
        conditions. This will generate a policy with two main statements for the effect:
        one statement for Allow and one statement for Deny.
        Methods that includes conditions will have their own statement in the policy."""
        if (self.allowMethods is None or len(self.allowMethods) == 0) and (
            self.denyMethods is None or len(self.denyMethods) == 0
        ):
            raise NameError("No statements defined for the policy")

        policy = {
            "principalId": self.principalId,
            "policyDocument": {"Version": self.version, "Statement": []},
        }

        policy["policyDocument"]["Statement"].extend(
            self._getStatementForEffect("Allow", self.allowMethods)
        )
        policy["policyDocument"]["Statement"].extend(
            self._getStatementForEffect("Deny", self.denyMethods)
        )

        return policy
