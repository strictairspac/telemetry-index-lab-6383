from fastapi import APIRouter,Depends
from src.middlewares.auth import current,writer
from src.schemas.business import SampleImportInput
from src.services import samples
from src.controllers.business import import_samples
router=APIRouter()
@router.get('/samples')
def listing(u=Depends(current)):return samples.list_items()
@router.get('/samples/current')
def current_batch(u=Depends(current)):return samples.current()
@router.post('/samples/import')
def import_batch(data:SampleImportInput,u=Depends(writer)):return import_samples(data,u)
