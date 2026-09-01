# azentspublicclient.TerminalV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**terminal_v1_get_terminal_projection**](TerminalV1Api.md#terminal_v1_get_terminal_projection) | **GET** /terminal/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id} | Get Terminal Projection
[**terminal_v1_issue_terminal_ticket**](TerminalV1Api.md#terminal_v1_issue_terminal_ticket) | **POST** /terminal/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/ticket | Issue Terminal Ticket


# **terminal_v1_get_terminal_projection**
> RuntimeTerminalProjectionResponse terminal_v1_get_terminal_projection(handle, agent_id, session_id)

Get Terminal Projection

Return current Terminal availability without starting the Runtime.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_terminal_projection_response import RuntimeTerminalProjectionResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.TerminalV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    session_id = 'session_id_example' # str | 

    try:
        # Get Terminal Projection
        api_response = api_instance.terminal_v1_get_terminal_projection(handle, agent_id, session_id)
        print("The response of TerminalV1Api->terminal_v1_get_terminal_projection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling TerminalV1Api->terminal_v1_get_terminal_projection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **session_id** | **str**|  | 

### Return type

[**RuntimeTerminalProjectionResponse**](RuntimeTerminalProjectionResponse.md)

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

# **terminal_v1_issue_terminal_ticket**
> RuntimeTerminalTicketResponse terminal_v1_issue_terminal_ticket(handle, agent_id, session_id)

Issue Terminal Ticket

Issue a one-time resource-bound ticket without Runtime auto-start.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_terminal_ticket_response import RuntimeTerminalTicketResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.TerminalV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    session_id = 'session_id_example' # str | 

    try:
        # Issue Terminal Ticket
        api_response = api_instance.terminal_v1_issue_terminal_ticket(handle, agent_id, session_id)
        print("The response of TerminalV1Api->terminal_v1_issue_terminal_ticket:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling TerminalV1Api->terminal_v1_issue_terminal_ticket: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **session_id** | **str**|  | 

### Return type

[**RuntimeTerminalTicketResponse**](RuntimeTerminalTicketResponse.md)

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

