# LLMProviderIntegrationResponseConfig


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
**connected_at** | **datetime** |  | 
**last_refreshed_at** | **datetime** |  | 
**last_failed_at** | **datetime** |  | 
**last_failure_reason** | **str** |  | 
**entitlement_status** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.llm_provider_integration_response_config import LLMProviderIntegrationResponseConfig

# TODO update the JSON string below
json = "{}"
# create an instance of LLMProviderIntegrationResponseConfig from a JSON string
llm_provider_integration_response_config_instance = LLMProviderIntegrationResponseConfig.from_json(json)
# print the JSON string representation of the object
print(LLMProviderIntegrationResponseConfig.to_json())

# convert the object into a dict
llm_provider_integration_response_config_dict = llm_provider_integration_response_config_instance.to_dict()
# create an instance of LLMProviderIntegrationResponseConfig from a dict
llm_provider_integration_response_config_from_dict = LLMProviderIntegrationResponseConfig.from_dict(llm_provider_integration_response_config_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


