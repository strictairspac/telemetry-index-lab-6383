from sqlalchemy import Column,Integer,String,DateTime,func
from src.config.database import Base
class SampleBatch(Base):
 __tablename__='sample_batches'
 id=Column(Integer,primary_key=True)
 batch_no=Column(String(60),unique=True,nullable=False)
 content_hash=Column(String(64),nullable=False)
 row_count=Column(Integer,nullable=False,default=0)
 status=Column(String(20),nullable=False,default='importing')
 table_name=Column(String(64),nullable=False,default='')
 error=Column(String(1000),nullable=True)
 created_at=Column(DateTime,server_default=func.now())
 activated_at=Column(DateTime,nullable=True)
