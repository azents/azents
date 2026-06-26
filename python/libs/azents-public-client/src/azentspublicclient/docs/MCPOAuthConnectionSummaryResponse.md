# MCPOAuthConnectionSummaryResponse

MCP OAuth connection summary response model.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**status** | [**MCPOAuthConnectionStatus**](MCPOAuthConnectionStatus.md) |  | 
**issuer** | **str** |  | [optional] 
**resource** | **str** |  | [optional] 
**scope** | **str** |  | [optional] 
**expires_at** | **datetime** |  | [optional] 

## Example

```python
from azentspublicclient.models.mcpo_auth_connection_summary_response import MCPOAuthConnectionSummaryResponse

# TODO update the JSON string below
json = "{}"
# create an instance of MCPOAuthConnectionSummaryResponse from a JSON string
mcpo_auth_connection_summary_response_instance = MCPOAuthConnectionSummaryResponse.from_json(json)
# print the JSON string representation of the object
print(MCPOAuthConnectionSummaryResponse.to_json())

# convert the object into a dict
mcpo_auth_connection_summary_response_dict = mcpo_auth_connection_summary_response_instance.to_dict()
# create an instance of MCPOAuthConnectionSummaryResponse from a dict
mcpo_auth_connection_summary_response_from_dict = MCPOAuthConnectionSummaryResponse.from_dict(mcpo_auth_connection_summary_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


