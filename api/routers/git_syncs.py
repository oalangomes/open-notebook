from typing import List

from fastapi import APIRouter, HTTPException
from loguru import logger

from api.git_sync_service import GitSyncService
from api.models import (
    GitSyncCreateRequest,
    GitSyncResponse,
    GitSyncRunResponse,
    GitSyncUpdateRequest,
)

router = APIRouter(prefix="/git-syncs", tags=["git-syncs"])


@router.get("", response_model=List[GitSyncResponse])
async def list_git_syncs():
    try:
        return await GitSyncService.list_syncs()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing git syncs: {e}")
        raise HTTPException(status_code=500, detail="Failed to list git syncs")


@router.post("", response_model=GitSyncResponse, status_code=201)
async def create_git_sync(request: GitSyncCreateRequest):
    try:
        return await GitSyncService.create_sync(request)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating git sync: {e}")
        raise HTTPException(status_code=500, detail="Failed to create git sync")


@router.get("/{sync_id}", response_model=GitSyncResponse)
async def get_git_sync(sync_id: str):
    try:
        return await GitSyncService.get_sync(sync_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching git sync {sync_id}: {e}")
        raise HTTPException(status_code=404, detail="Git sync not found")


@router.put("/{sync_id}", response_model=GitSyncResponse)
async def update_git_sync(sync_id: str, request: GitSyncUpdateRequest):
    try:
        return await GitSyncService.update_sync(sync_id, request)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating git sync {sync_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update git sync")


@router.post("/{sync_id}/run", response_model=GitSyncRunResponse)
async def run_git_sync(sync_id: str):
    try:
        return await GitSyncService.run_sync(sync_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error running git sync {sync_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to run git sync")
