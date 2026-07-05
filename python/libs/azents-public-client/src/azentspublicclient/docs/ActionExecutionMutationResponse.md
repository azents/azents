# ActionExecutionMutationResponse

Action execution mutation response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**requested** | **bool** | Whether a state transition was requested | 
**action_execution** | [**ActionExecutionProjectionResponse**](ActionExecutionProjectionResponse.md) | Updated action execution projection | 

## Example

```python
from azentspublicclient.models.action_execution_mutation_response import ActionExecutionMutationResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ActionExecutionMutationResponse from a JSON string
action_execution_mutation_response_instance = ActionExecutionMutationResponse.from_json(json)
# print the JSON string representation of the object
print(ActionExecutionMutationResponse.to_json())

# convert the object into a dict
action_execution_mutation_response_dict = action_execution_mutation_response_instance.to_dict()
# create an instance of ActionExecutionMutationResponse from a dict
action_execution_mutation_response_from_dict = ActionExecutionMutationResponse.from_dict(action_execution_mutation_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


