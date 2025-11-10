from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

kv_name = "Dacgenai-7"
kv_uri = f"https://{kv_name}.vault.azure.net"
creds = DefaultAzureCredential()
client = SecretClient(vault_url=kv_uri, credential=creds)
CONFIG = {
    "search_endpoint": client.get_secret("AZURE-SEARCH-ENDPOINT").value,
    "search_key": client.get_secret("AZURE-SEARCH-KEY").value,
    "search_index": client.get_secret("AZURE-SEARCH-INDEX").value,
    "vision_endpoint": client.get_secret("AZURE-VISION-ENDPOINT").value,
    "vision_key": client.get_secret("AZURE-VISION-KEY").value,
    "adls_connection_string": client.get_secret("AZURE-ADLS-CONNECTION-STRING").value,
    "adls_container": client.get_secret("AZURE-ADLS-CONTAINER").value,
    "table_name": client.get_secret("TABLE-NAME").value,
    "openai_endpoint": client.get_secret("AZURE-OPENAI-ENDPOINT").value,
    "openai_api_key": client.get_secret("AZURE-OPENAI-API-KEY").value,
    "deployment_name": client.get_secret("DEPLOYMENT-NAME").value,
    "openai_api_version": client.get_secret("AZURE-OPENAI-API-VERSION").value,
    "redis_url": client.get_secret("AZURE-REDIS-URL").value,
    "redis_password": client.get_secret("AZURE-REDIS-PASSWORD").value,
    "redis_port": client.get_secret("AZURE-REDIS-PORT").value
}

def test():
    return "hello there"