from pydantic import BaseModel, ConfigDict


class ErrorDetail(BaseModel):
  code: str
  message: str


class ErrorResponse(BaseModel):
  model_config = ConfigDict(
    json_schema_extra={
      "examples": [{"error": {"code": "not_found", "message": "Repository not found"}}]
    }
  )

  error: ErrorDetail
