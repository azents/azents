# SessionInitializationResponse

Session initialization live projection response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Session initialization ID | 
**status** | **str** | Initialization status | 
**failure_summary** | **str** |  | [optional] 
**retry_count** | **int** | Retry count | 
**started_at** | **datetime** |  | [optional] 
**completed_at** | **datetime** |  | [optional] 
**failed_at** | **datetime** |  | [optional] 
**canceled_at** | **datetime** |  | [optional] 
**cleaned_at** | **datetime** |  | [optional] 
**updated_at** | **datetime** | Updated time | 
**steps** | [**List[SessionInitializationStepResponse]**](SessionInitializationStepResponse.md) | Current initialization steps | 

## Example

```python
from azentspublicclient.models.session_initialization_response import SessionInitializationResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SessionInitializationResponse from a JSON string
session_initialization_response_instance = SessionInitializationResponse.from_json(json)
# print the JSON string representation of the object
print(SessionInitializationResponse.to_json())

# convert the object into a dict
session_initialization_response_dict = session_initialization_response_instance.to_dict()
# create an instance of SessionInitializationResponse from a dict
session_initialization_response_from_dict = SessionInitializationResponse.from_dict(session_initialization_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


