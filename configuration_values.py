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
  
# DEPRECATED - kept commented out for examples and notes - use the /website-settings API endpoint instead which reads from the new website_settings table in the database
#   @staticmethod
#   def get_websites():
#       return [
#           {"name": "cdcfoundation", "url": "https://www.cdcfoundation.org/request-for-proposals"},
#           {"name": "nnphi", "url": "https://nnphi.org/news/funding-announcements/"},
#           {"name": "astho", "url": "https://www.astho.org/members/opportunities/"},
#           {"name": "cste", "url": "https://resources.cste.org/rfp/home/rfp"},
#           {"name": "aira", "url": "https://www.immregistries.org/opportunities"},
#           {"name": "ny", "url": "https://www.health.ny.gov/funding/"},
#           {"name": "md", "url": "https://health.maryland.gov/procumnt/pages/procopps.aspx#:~:text=Solicitation%20Title,Date%2FTime%206%2F14%2F2023%202%3A00%20PM%20Attachment"},
#           {"name": "tn", "url": "https://www.tn.gov/generalservices/procurement/central-procurement-office--cpo-/supplier-information/request-for-proposals--rfp--opportunities1"},
#           {"name": "cdcfoundation", "url": "https://web.archive.org/web/20250113003138/https://www.cdcfoundation.org/request-for-proposals"},
#           {"name": "nnphi", "url": "nothing"},
#           {"name": "astho", "url": "https://web.archive.org/web/20250118131712/https://www.astho.org/members/opportunities/"},
#           {"name": "cste", "url": "https://web.archive.org/web/20200424184250/https://www.cste.org/page/RFP"},
#           {"name": "aira", "url": "https://www.immregistries.org/opportunities"},
#       ]
  
############# Good candidates

#DE
# https://mmp.delaware.gov/Bids/

#IL
# https://hfs.illinois.gov/info/procurement.html#:~:text=It%20is%20the%20State%E2%80%99s%20primary,on%20procurement%20rules%20and%20requirements


############## Maybes

#GA
# Need to figure out sorting https://ssl.doas.state.ga.us/gpr/index

#CO
# Need to figure out sorting https://www.bidscolorado.com/co/portal.nsf/xpPAViewSolOpenbyNumber.xsp

#NE
# Sorting https://das.nebraska.gov/materiel/bid-opportunities.html#:~:text=Vital%20Records%20Management%20System%2005%2F22%2F25,Health%20and%20Human%20Services%2005%2F22%2F2025



############### Ignore - these have issues

#AR
# Very little activity https://arbuy.arkansas.gov/bso/view/search/external/advancedSearchBid.xhtml?openBids=true

#MS
# Bot protection https://procurement.opengov.com/portal/msdh
