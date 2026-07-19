# XaiSubscriptionFinancialDetailsResponse

Management-only xAI subscription financial details.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  |
**prepaid_balance_cents** | **int** |  |
**payg_cap_cents** | **int** |  |
**payg_used_cents** | **int** |  |
**auto_top_up_enabled** | **bool** |  |
**auto_top_up_amount_cents** | **int** |  |
**auto_top_up_monthly_maximum_cents** | **int** |  |

## Example

```python
from azentspublicclient.models.xai_subscription_financial_details_response import XaiSubscriptionFinancialDetailsResponse

# TODO update the JSON string below
json = "{}"
# create an instance of XaiSubscriptionFinancialDetailsResponse from a JSON string
xai_subscription_financial_details_response_instance = XaiSubscriptionFinancialDetailsResponse.from_json(json)
# print the JSON string representation of the object
print(XaiSubscriptionFinancialDetailsResponse.to_json())

# convert the object into a dict
xai_subscription_financial_details_response_dict = xai_subscription_financial_details_response_instance.to_dict()
# create an instance of XaiSubscriptionFinancialDetailsResponse from a dict
xai_subscription_financial_details_response_from_dict = XaiSubscriptionFinancialDetailsResponse.from_dict(xai_subscription_financial_details_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
