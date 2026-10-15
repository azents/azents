import SwiftUI

struct WelcomeView: View {
  var body: some View {
    VStack(spacing: 16) {
      Text("Azents")
        .font(.title)
        .accessibilityAddTraits(.isHeader)
      Text("Hello, world!")
        .accessibilityIdentifier("hello-world-message")
    }
    .padding()
  }
}
