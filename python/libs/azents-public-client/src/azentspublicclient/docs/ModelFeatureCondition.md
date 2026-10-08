# ModelFeatureCondition

Constrain a present feature without defining a second support fact.  Null means that a request dimension is unconstrained. Consumers evaluate these conditions against the complete effective request, never raw settings.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**feature** | [**ModelCapabilityFeature**](ModelCapabilityFeature.md) |  | 
**reasoning_efforts** | [**List[ReasoningEffortValue]**](ReasoningEffortValue.md) |  | 
**function_tools** | **bool** |  | 

## Example

```python
from azentspublicclient.models.model_feature_condition import ModelFeatureCondition

# TODO update the JSON string below
json = "{}"
# create an instance of ModelFeatureCondition from a JSON string
model_feature_condition_instance = ModelFeatureCondition.from_json(json)
# print the JSON string representation of the object
print(ModelFeatureCondition.to_json())

# convert the object into a dict
model_feature_condition_dict = model_feature_condition_instance.to_dict()
# create an instance of ModelFeatureCondition from a dict
model_feature_condition_from_dict = ModelFeatureCondition.from_dict(model_feature_condition_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


