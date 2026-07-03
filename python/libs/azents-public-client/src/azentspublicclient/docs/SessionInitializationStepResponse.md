# SessionInitializationStepResponse

Session initialization step response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Session initialization step ID | 
**sequence** | **int** | Stable step order | 
**step_key** | **str** | Stable step key | 
**step_type** | **str** | Typed step kind | 
**status** | **str** | Step status | 
**blocking** | **bool** | Whether failure blocks run dispatch | 
**retryable** | **bool** | Whether retry is allowed | 
**attempt** | **int** | Current attempt number | 
**depends_on_step_keys** | **List[str]** | Dependency step keys | 
**resource_descriptors** | **List[object]** | Created resources | 
**failure_reason** | **str** |  | [optional] 
**started_at** | **datetime** |  | [optional] 
**completed_at** | **datetime** |  | [optional] 
**failed_at** | **datetime** |  | [optional] 
**created_at** | **datetime** | Created time | 
**updated_at** | **datetime** | Updated time | 

## Example

```python
from azentspublicclient.models.session_initialization_step_response import SessionInitializationStepResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SessionInitializationStepResponse from a JSON string
session_initialization_step_response_instance = SessionInitializationStepResponse.from_json(json)
# print the JSON string representation of the object
print(SessionInitializationStepResponse.to_json())

# convert the object into a dict
session_initialization_step_response_dict = session_initialization_step_response_instance.to_dict()
# create an instance of SessionInitializationStepResponse from a dict
session_initialization_step_response_from_dict = SessionInitializationStepResponse.from_dict(session_initialization_step_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


