# LLMProviderIntegrationCreateRequestConfig


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'aws_credentials']
**access_key_id** | **str** | AWS Access Key ID | 
**region** | **str** | GCP region | 
**role_arn** | **str** |  | [optional] 
**project_id** | **str** | GCP project ID | 
**account_id** | **str** |  | [optional] 
**email** | **str** |  | [optional] 
**plan_type** | **str** |  | [optional] 
**connection_method** | **str** | Connection method | 
**status** | **str** | Connection status | 
**connected_at** | **datetime** |  | [optional] 
**last_refreshed_at** | **datetime** |  | [optional] 
**last_failed_at** | **datetime** |  | [optional] 
**last_failure_reason** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.llm_provider_integration_create_request_config import LLMProviderIntegrationCreateRequestConfig

# TODO update the JSON string below
json = "{}"
# create an instance of LLMProviderIntegrationCreateRequestConfig from a JSON string
llm_provider_integration_create_request_config_instance = LLMProviderIntegrationCreateRequestConfig.from_json(json)
# print the JSON string representation of the object
print(LLMProviderIntegrationCreateRequestConfig.to_json())

# convert the object into a dict
llm_provider_integration_create_request_config_dict = llm_provider_integration_create_request_config_instance.to_dict()
# create an instance of LLMProviderIntegrationCreateRequestConfig from a dict
llm_provider_integration_create_request_config_from_dict = LLMProviderIntegrationCreateRequestConfig.from_dict(llm_provider_integration_create_request_config_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


