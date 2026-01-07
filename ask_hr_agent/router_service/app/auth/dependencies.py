from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import settings
from app.auth.ibm_verify import IBMVerifyValidator
from app.models.dto import UserContext

security = HTTPBearer()
validator = IBMVerifyValidator(settings.IBM_VERIFY_ISSUER, settings.IBM_VERIFY_CLIENT_ID)


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> UserContext:
    token = credentials.credentials
    try:
        claims = await validator.validate_token(token)
        return UserContext(
            user_id=claims.get("sub"),
            worker_id=claims.get("employeeNumber", "UNKNOWN"),
            email=claims.get("email"),
            name=claims.get("name"),
            roles=claims.get("groups", []),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
