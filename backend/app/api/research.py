"""Local foundation APIs. No approval grant or external dispatch endpoint exists."""
from typing import Annotated
from fastapi import APIRouter,Request,Query,Path
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.schemas.research import JobCreate,JobControl

class SafeResearchRoute(APIRoute):
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def safe(request):
            try:return await handler(request)
            except RequestValidationError:
                # Pydantic's default errors include rejected input; never echo it.
                return JSONResponse(status_code=422,content={'detail':'Invalid research input. Use public category/place text, bounded coordinates, explicit disabled external scopes, valid limits and a timezone-aware expiry.'})
        return safe

router=APIRouter(prefix='/api/research',route_class=SafeResearchRoute)
Identifier=Annotated[int,Path(ge=1,le=9007199254740991)]
def manager(request):return request.app.state.research_manager

@router.get('/status')
def status(request:Request):return manager(request).status()

@router.post('/jobs',status_code=201)
def create(payload:JobCreate,request:Request):return manager(request).create(payload)

@router.get('/jobs')
def jobs(request:Request,limit:int=Query(20,ge=1,le=50),offset:int=Query(0,ge=0,le=1000000000)):
    return manager(request).listing(limit,offset)

@router.get('/jobs/{identifier}')
def detail(identifier:Identifier,request:Request):return manager(request).read(identifier)

@router.post('/jobs/{identifier}/control')
def control(identifier:Identifier,payload:JobControl,request:Request):return manager(request).control(identifier,payload)

@router.get('/jobs/{identifier}/events')
def events(identifier:Identifier,request:Request,limit:int=Query(50,ge=1,le=100),after:int=Query(0,ge=0,le=9007199254740991)):
    return manager(request).events(identifier,limit,after)
