import XCTest

final class AzentsUITests: XCTestCase {
  @MainActor
  func testLaunchShowsHelloWorld() throws {
    let app = XCUIApplication()
    app.launch()

    let message = app.staticTexts["hello-world-message"]
    XCTAssertTrue(message.waitForExistence(timeout: 5))
    XCTAssertEqual(message.label, "Hello, world!")
    XCTAssertTrue(app.staticTexts["Azents"].exists)

    let screenshot = XCTAttachment(screenshot: app.screenshot())
    screenshot.name = "Hello World"
    screenshot.lifetime = .keepAlways
    add(screenshot)
  }
}
