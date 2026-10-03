# CatalogPriceRules


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**rates** | [**List[CatalogPriceRate]**](CatalogPriceRate.md) |  | 
**off_peak** | [**CatalogOffPeakRule**](CatalogOffPeakRule.md) |  | 
**issues** | [**List[CatalogPriceIssue]**](CatalogPriceIssue.md) |  | 

## Example

```python
from azentspublicclient.models.catalog_price_rules import CatalogPriceRules

# TODO update the JSON string below
json = "{}"
# create an instance of CatalogPriceRules from a JSON string
catalog_price_rules_instance = CatalogPriceRules.from_json(json)
# print the JSON string representation of the object
print(CatalogPriceRules.to_json())

# convert the object into a dict
catalog_price_rules_dict = catalog_price_rules_instance.to_dict()
# create an instance of CatalogPriceRules from a dict
catalog_price_rules_from_dict = CatalogPriceRules.from_dict(catalog_price_rules_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


