# CatalogOffPeakRule


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**windows** | [**List[CatalogTimeWindow]**](CatalogTimeWindow.md) |  | 
**weekday_timezone** | **str** |  | 
**overrides** | [**List[CatalogPriceRate]**](CatalogPriceRate.md) |  | 

## Example

```python
from azentspublicclient.models.catalog_off_peak_rule import CatalogOffPeakRule

# TODO update the JSON string below
json = "{}"
# create an instance of CatalogOffPeakRule from a JSON string
catalog_off_peak_rule_instance = CatalogOffPeakRule.from_json(json)
# print the JSON string representation of the object
print(CatalogOffPeakRule.to_json())

# convert the object into a dict
catalog_off_peak_rule_dict = catalog_off_peak_rule_instance.to_dict()
# create an instance of CatalogOffPeakRule from a dict
catalog_off_peak_rule_from_dict = CatalogOffPeakRule.from_dict(catalog_off_peak_rule_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


