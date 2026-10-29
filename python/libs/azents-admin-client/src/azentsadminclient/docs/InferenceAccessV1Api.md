# azentsadminclient.InferenceAccessV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**inference_access_v1_inspect_subject**](InferenceAccessV1Api.md#inference_access_v1_inspect_subject) | **GET** /llm-access/v1/agents/{agent_id}/supply | Inspect Subject
[**inference_access_v1_inspect_supply**](InferenceAccessV1Api.md#inference_access_v1_inspect_supply) | **GET** /llm-access/v1/supplies/{supply_id} | Inspect Supply
[**inference_access_v1_issue**](InferenceAccessV1Api.md#inference_access_v1_issue) | **POST** /llm-access/v1/supplies | Issue
[**inference_access_v1_revoke_supply**](InferenceAccessV1Api.md#inference_access_v1_revoke_supply) | **DELETE** /llm-access/v1/supplies/{supply_id} | Revoke Supply
[**inference_access_v1_revoke_token**](InferenceAccessV1Api.md#inference_access_v1_revoke_token) | **DELETE** /llm-access/v1/supplies/{supply_id}/tokens/{token_id} | Revoke Token
[**inference_access_v1_rotate**](InferenceAccessV1Api.md#inference_access_v1_rotate) | **POST** /llm-access/v1/rotate | Rotate


# **inference_access_v1_inspect_subject**
> SupplyState inference_access_v1_inspect_subject(agent_id, subject)

Inspect Subject

Inspect an existing supply after an uncertain issuance response.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.supply_state import SupplyState
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.InferenceAccessV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    subject = 'subject_example' # str | 

    try:
        # Inspect Subject
        api_response = api_instance.inference_access_v1_inspect_subject(agent_id, subject)
        print("The response of InferenceAccessV1Api->inference_access_v1_inspect_subject:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling InferenceAccessV1Api->inference_access_v1_inspect_subject: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **subject** | **str**|  | 

### Return type

[**SupplyState**](SupplyState.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **inference_access_v1_inspect_supply**
> SupplyState inference_access_v1_inspect_supply(supply_id)

Inspect Supply

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.supply_state import SupplyState
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.InferenceAccessV1Api(api_client)
    supply_id = 'supply_id_example' # str | 

    try:
        # Inspect Supply
        api_response = api_instance.inference_access_v1_inspect_supply(supply_id)
        print("The response of InferenceAccessV1Api->inference_access_v1_inspect_supply:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling InferenceAccessV1Api->inference_access_v1_inspect_supply: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **supply_id** | **str**|  | 

### Return type

[**SupplyState**](SupplyState.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **inference_access_v1_issue**
> IssuedToken inference_access_v1_issue(token_issue_request)

Issue

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.issued_token import IssuedToken
from azentsadminclient.models.token_issue_request import TokenIssueRequest
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.InferenceAccessV1Api(api_client)
    token_issue_request = azentsadminclient.TokenIssueRequest() # TokenIssueRequest | 

    try:
        # Issue
        api_response = api_instance.inference_access_v1_issue(token_issue_request)
        print("The response of InferenceAccessV1Api->inference_access_v1_issue:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling InferenceAccessV1Api->inference_access_v1_issue: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **token_issue_request** | [**TokenIssueRequest**](TokenIssueRequest.md)|  | 

### Return type

[**IssuedToken**](IssuedToken.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**201** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **inference_access_v1_revoke_supply**
> inference_access_v1_revoke_supply(supply_id)

Revoke Supply

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.InferenceAccessV1Api(api_client)
    supply_id = 'supply_id_example' # str | 

    try:
        # Revoke Supply
        api_instance.inference_access_v1_revoke_supply(supply_id)
    except Exception as e:
        print("Exception when calling InferenceAccessV1Api->inference_access_v1_revoke_supply: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **supply_id** | **str**|  | 

### Return type

void (empty response body)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **inference_access_v1_revoke_token**
> inference_access_v1_revoke_token(supply_id, token_id)

Revoke Token

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.InferenceAccessV1Api(api_client)
    supply_id = 'supply_id_example' # str | 
    token_id = 'token_id_example' # str | 

    try:
        # Revoke Token
        api_instance.inference_access_v1_revoke_token(supply_id, token_id)
    except Exception as e:
        print("Exception when calling InferenceAccessV1Api->inference_access_v1_revoke_token: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **supply_id** | **str**|  | 
 **token_id** | **str**|  | 

### Return type

void (empty response body)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **inference_access_v1_rotate**
> IssuedToken inference_access_v1_rotate(token_rotate_request)

Rotate

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.issued_token import IssuedToken
from azentsadminclient.models.token_rotate_request import TokenRotateRequest
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.InferenceAccessV1Api(api_client)
    token_rotate_request = azentsadminclient.TokenRotateRequest() # TokenRotateRequest | 

    try:
        # Rotate
        api_response = api_instance.inference_access_v1_rotate(token_rotate_request)
        print("The response of InferenceAccessV1Api->inference_access_v1_rotate:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling InferenceAccessV1Api->inference_access_v1_rotate: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **token_rotate_request** | [**TokenRotateRequest**](TokenRotateRequest.md)|  | 

### Return type

[**IssuedToken**](IssuedToken.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

