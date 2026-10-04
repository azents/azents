# ModelRequestConstraints

Known request metadata, independent of final feature membership.  A missing default is omitted knowledge, not another feature support state. The final capability fields alone determine whether a feature is present.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**known_default** | [**ReasoningEffortValue**](ReasoningEffortValue.md) |  | [optional] 
**feature_conditions** | [**List[ModelFeatureCondition]**](ModelFeatureCondition.md) |  | [optional] 

## Example

```python
from azentspublicclient.models.model_request_constraints import ModelRequestConstraints

# TODO update the JSON string below
json = "{}"
# create an instance of ModelRequestConstraints from a JSON string
model_request_constraints_instance = ModelRequestConstraints.from_json(json)
# print the JSON string representation of the object
print(ModelRequestConstraints.to_json())

# convert the object into a dict
model_request_constraints_dict = model_request_constraints_instance.to_dict()
# create an instance of ModelRequestConstraints from a dict
model_request_constraints_from_dict = ModelRequestConstraints.from_dict(model_request_constraints_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


