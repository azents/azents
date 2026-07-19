# OpenRouterSubscriptionFinancialDetailsResponse

Management-only OpenRouter API-key credit details.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  |
**credit_limit** | **float** |  |
**credit_remaining** | **float** |  |
**usage** | **float** |  |
**usage_daily** | **float** |  |
**usage_weekly** | **float** |  |
**usage_monthly** | **float** |  |
**limit_reset** | **str** |  |
**include_byok_in_limit** | **bool** |  |

## Example

```python
from azentspublicclient.models.open_router_subscription_financial_details_response import OpenRouterSubscriptionFinancialDetailsResponse

# TODO update the JSON string below
json = "{}"
# create an instance of OpenRouterSubscriptionFinancialDetailsResponse from a JSON string
open_router_subscription_financial_details_response_instance = OpenRouterSubscriptionFinancialDetailsResponse.from_json(json)
# print the JSON string representation of the object
print(OpenRouterSubscriptionFinancialDetailsResponse.to_json())

# convert the object into a dict
open_router_subscription_financial_details_response_dict = open_router_subscription_financial_details_response_instance.to_dict()
# create an instance of OpenRouterSubscriptionFinancialDetailsResponse from a dict
open_router_subscription_financial_details_response_from_dict = OpenRouterSubscriptionFinancialDetailsResponse.from_dict(open_router_subscription_financial_details_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
