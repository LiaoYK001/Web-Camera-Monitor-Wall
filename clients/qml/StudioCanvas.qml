import QtQuick
import QtQuick.Controls

Item {
    id: root
    property var sceneModel
    property bool editMode: true

    Rectangle {
        id: canvas
        anchors.centerIn: parent
        width: Math.min(parent.width, parent.height * sceneModel.canvasWidth / sceneModel.canvasHeight)
        height: width * sceneModel.canvasHeight / sceneModel.canvasWidth
        color: "black"
        clip: true

        Repeater {
            model: sceneModel
            delegate: Rectangle {
                required property int index
                required property string kind
                required property string name
                required property real sceneX
                required property real sceneY
                required property real sceneWidth
                required property real sceneHeight
                required property real sceneRotation
                required property real sceneOpacity
                required property bool sceneVisible
                required property bool sceneLocked
                required property int sceneZ
                required property string sourceText
                required property string sourceColor
                x: sceneX * canvas.width / sceneModel.canvasWidth
                y: sceneY * canvas.height / sceneModel.canvasHeight
                width: sceneWidth * canvas.width / sceneModel.canvasWidth
                height: sceneHeight * canvas.height / sceneModel.canvasHeight
                rotation: sceneRotation
                opacity: sceneOpacity
                visible: sceneVisible
                z: sceneZ
                color: kind === "color" ? sourceColor : "#18202b"
                border.color: root.editMode && !sceneLocked ? "#46a6ff" : "transparent"
                Text {
                    anchors.centerIn: parent
                    color: "white"
                    text: kind === "text" ? sourceText : name
                    elide: Text.ElideRight
                }
                DragHandler {
                    enabled: root.editMode && !sceneLocked
                    onActiveChanged: if (!active) sceneModel.moveItem(index,
                        parent.x * sceneModel.canvasWidth / canvas.width,
                        parent.y * sceneModel.canvasHeight / canvas.height)
                }
            }
        }
    }
}
