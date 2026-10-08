# CatalogPriceIssue

A required but uninterpretable dimension that prevents a partial total.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**source_field** | **str** |  | 
**metrics** | [**List[PriceMetric]**](PriceMetric.md) |  | 
**dimension** | **str** |  | 
**invalid** | **bool** |  | 

## Example

```python
from azentspublicclient.models.catalog_price_issue import CatalogPriceIssue

# TODO update the JSON string below
json = "{}"
# create an instance of CatalogPriceIssue from a JSON string
catalog_price_issue_instance = CatalogPriceIssue.from_json(json)
# print the JSON string representation of the object
print(CatalogPriceIssue.to_json())

# convert the object into a dict
catalog_price_issue_dict = catalog_price_issue_instance.to_dict()
# create an instance of CatalogPriceIssue from a dict
catalog_price_issue_from_dict = CatalogPriceIssue.from_dict(catalog_price_issue_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


