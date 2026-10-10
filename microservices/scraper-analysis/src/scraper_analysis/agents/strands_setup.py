"""Strands Agents SDK factory. Bedrock is Strands' default model provider --
swapping providers later (Anthropic/OpenAI/etc.) is a one-line change here,
not a pipeline rewrite.

NOTE: `strands-agents` ships 100+ dependencies including botocore; import it
lazily so the rest of this service (adapters, API, tests) works even before
the package is installed / before AWS credentials are configured.
"""

from ..config import get_settings


def build_bedrock_agent(system_prompt: str):
    import boto3
    from strands import Agent
    from strands.models import BedrockModel

    settings = get_settings()

    # pydantic-settings loads .env into this process's Settings object but
    # never exports it to os.environ, so BedrockModel's default boto3
    # session would silently fall back to the ambient AWS CLI identity
    # (no Bedrock access) instead of the STS creds configured here --
    # confirmed via a live AccessDeniedException naming the wrong IAM
    # user. Build the session explicitly instead of relying on the chain.
    session = boto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        aws_session_token=settings.aws_session_token,
        region_name=settings.aws_default_region,
    )
    model = BedrockModel(
        model_id=settings.bedrock_model_id,
        boto_session=session,
        # This account's IAM user only has bedrock:InvokeModel, not
        # bedrock:InvokeModelWithResponseStream (Strands streams by
        # default) -- confirmed via a live AccessDeniedException.
        streaming=False,
    )
    return Agent(model=model, system_prompt=system_prompt)
