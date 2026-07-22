from typing import Optional
import aio_pika
from app.config import settings


class MessageBroker:
    """Message broker com RabbitMQ/AMQP"""
    
    def __init__(self):
        self.connection = None
        self.channel = None
    
    async def connect(self) -> None:
        """Conectar ao message broker"""
        self.connection = await aio_pika.connect_robust(settings.celery_broker_url)
        self.channel = await self.connection.channel()
    
    async def disconnect(self) -> None:
        """Desconectar do message broker"""
        if self.connection:
            await self.connection.close()
    
    async def publish(self, queue_name: str, message: dict) -> None:
        """Publicar mensagem"""
        if not self.channel:
            return
        
        exchange = await self.channel.declare_exchange(
            queue_name,
            aio_pika.ExchangeType.DIRECT,
            durable=True,
        )
        
        queue = await self.channel.declare_queue(queue_name, durable=True)
        await queue.bind(exchange, queue_name)
        
        # Publicar mensagem
        import json
        await exchange.publish(
            aio_pika.Message(body=json.dumps(message).encode()),
            routing_key=queue_name,
        )


broker = MessageBroker()


__all__ = ["MessageBroker", "broker"]
