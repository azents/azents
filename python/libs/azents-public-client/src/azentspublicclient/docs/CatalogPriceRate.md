# CatalogPriceRate

A whole-quantity tariff, not a progressive marginal bracket.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**metric** | [**PriceMetric**](PriceMetric.md) |  | 
**tier** | [**PriceTier**](PriceTier.md) |  | 
**above_input_tokens** | **int** |  | 
**usd_per_unit** | **str** |  | 
**search_context_size** | **str** |  | 

## Example

```python
from azentspublicclient.models.catalog_price_rate import CatalogPriceRate

# TODO update the JSON string below
json = "{}"
# create an instance of CatalogPriceRate from a JSON string
catalog_price_rate_instance = CatalogPriceRate.from_json(json)
# print the JSON string representation of the object
print(CatalogPriceRate.to_json())

# convert the object into a dict
catalog_price_rate_dict = catalog_price_rate_instance.to_dict()
# create an instance of CatalogPriceRate from a dict
catalog_price_rate_from_dict = CatalogPriceRate.from_dict(catalog_price_rate_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


