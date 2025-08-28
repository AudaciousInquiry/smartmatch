import os;
from loguru import logger

class ConfigurationValues:

  @staticmethod
  def get_pgvector_connection():
      return os.environ['PGVECTOR_CONNECTION'] 

  @staticmethod
  def get_aws_secret_access_key():
      return os.environ['AWS_SECRET_ACCESS_KEY'] 

  @staticmethod
  def get_aws_access_key_id():
      return os.environ['AWS_ACCESS_KEY_ID'] 
  
  @staticmethod
  def get_aws_region_name():
      return os.environ['AWS_REGION_NAME'] 
  
  @staticmethod
  def get_aws_s3_bucket_name():
      return os.environ['AWS_S3_BUCKET_NAME'] 
  
  @staticmethod
  def get_embeddings_model():
      return os.environ['EMBEDDINGS_MODEL'] 
  
  @staticmethod
  def get_websites():
      return [
          #{"name": "cdcfoundation", "url": "https://www.cdcfoundation.org/request-for-proposals"},
          {"name": "nnphi", "url": "https://nnphi.org/news/funding-announcements/"},
          {"name": "astho", "url": "https://www.astho.org/members/opportunities/"},
          {"name": "cste", "url": "https://www.cste.org/page/RFP"},
          #{"name": "aira", "url": "https://www.immregistries.org/opportunities"},
          #{"name": "cdcfoundation", "url": "https://web.archive.org/web/20250113003138/https://www.cdcfoundation.org/request-for-proposals"},
          #{"name": "nnphi", "url": "nothing"},
          #{"name": "astho", "url": "https://web.archive.org/web/20250118131712/https://www.astho.org/members/opportunities/"},
          #{"name": "cste", "url": "https://web.archive.org/web/20200424184250/https://www.cste.org/page/RFP"},
          #{"name": "aira", "url": "https://www.immregistries.org/opportunities"},
      ]
  
