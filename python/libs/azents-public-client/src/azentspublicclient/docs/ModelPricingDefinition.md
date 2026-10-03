# ModelPricingDefinition

Compact normalized prices copied from a catalog into a saved selection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**rules** | [**CatalogPriceRules**](CatalogPriceRules.md) |  | 
**unavailable_reason** | [**ModelPricingUnavailableReason**](ModelPricingUnavailableReason.md) |  | 
**source_key** | **str** |  | 
**source_model_key** | **str** |  | 
**collected_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.model_pricing_definition import ModelPricingDefinition

# TODO update the JSON string below
json = "{}"
# create an instance of ModelPricingDefinition from a JSON string
model_pricing_definition_instance = ModelPricingDefinition.from_json(json)
# print the JSON string representation of the object
print(ModelPricingDefinition.to_json())

# convert the object into a dict
model_pricing_definition_dict = model_pricing_definition_instance.to_dict()
# create an instance of ModelPricingDefinition from a dict
model_pricing_definition_from_dict = ModelPricingDefinition.from_dict(model_pricing_definition_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


