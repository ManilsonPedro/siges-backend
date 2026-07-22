from typing import Optional
import redis.asyncio as redis
from app.config import settings


class RedisCache:
    """Serviço de Cache com Redis"""
    
    def __init__(self):
        self.redis = None
    
    async def connect(self) -> None:
        """Conectar ao Redis"""
        self.redis = await redis.from_url(settings.redis.url)
    
    async def disconnect(self) -> None:
        """Desconectar do Redis"""
        if self.redis:
            await self.redis.close()
    
    async def get(self, key: str) -> Optional[str]:
        """Obter valor do cache"""
        if not self.redis:
            return None
        return await self.redis.get(key)
    
    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        """Definir valor no cache"""
        if not self.redis:
            return
        ttl = ttl or settings.redis.ttl
        await self.redis.setex(key, ttl, value)
    
    async def delete(self, key: str) -> None:
        """Eliminar chave do cache"""
        if not self.redis:
            return
        await self.redis.delete(key)
    
    async def clear(self, pattern: str) -> None:
        """Limpar cache por padrão"""
        if not self.redis:
            return
        keys = await self.redis.keys(pattern)
        if keys:
            await self.redis.delete(*keys)


cache = RedisCache()


__all__ = ["RedisCache", "cache"]
