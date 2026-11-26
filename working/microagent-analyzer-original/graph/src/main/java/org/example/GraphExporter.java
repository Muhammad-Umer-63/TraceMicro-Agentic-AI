package org.example;

import guru.nidi.graphviz.attribute.*;
import guru.nidi.graphviz.engine.Format;
import guru.nidi.graphviz.engine.Graphviz;
import guru.nidi.graphviz.model.MutableGraph;
import guru.nidi.graphviz.model.MutableNode;

import java.io.File;
import java.io.IOException;
import java.util.*;

import static guru.nidi.graphviz.model.Factory.*;

/**
 * Exports class relationship graph to DOT and image formats
 */
public class GraphExporter {
    private final Graph graph;
    private final Map<RelationshipType, Color> relationshipColors = new HashMap<>();
    private int imageWidth = 4000; // Default width for high resolution
    
    public GraphExporter(Graph graph) {
        this.graph = graph;
        initializeColors();
    }
    
    public GraphExporter(Graph graph, int imageWidth) {
        this.graph = graph;
        this.imageWidth = imageWidth;
        initializeColors();
    }
    
    public void setImageWidth(int width) {
        this.imageWidth = width;
    }
    
    private void initializeColors() {
        // Define colors for different relationship types
        relationshipColors.put(RelationshipType.EXTENDS, Color.RED);
        relationshipColors.put(RelationshipType.IMPLEMENTS, Color.BLUE);
        relationshipColors.put(RelationshipType.CALLS, Color.GREEN);
        relationshipColors.put(RelationshipType.USES, Color.GRAY);
        relationshipColors.put(RelationshipType.REFERENCES, Color.LIGHTGREY);
        relationshipColors.put(RelationshipType.INJECTS, Color.ORANGE);
        relationshipColors.put(RelationshipType.ASSOCIATES, Color.PURPLE);
        relationshipColors.put(RelationshipType.ANNOTATED_WITH, Color.YELLOW);
        relationshipColors.put(RelationshipType.CREATES, Color.BROWN);
        relationshipColors.put(RelationshipType.DEPENDS_ON, Color.BLACK);
    }
    
    /**
     * Export the graph to DOT format
     */
    public void exportToDot(String outputFile) throws IOException {
        MutableGraph g = buildGraph();
        
        // Write DOT file
        String dotContent = g.toString();
        java.nio.file.Files.writeString(new File(outputFile).toPath(), dotContent);
        System.out.println("DOT file exported to: " + outputFile);
    }
    
    /**
     * Export the graph to image format (PNG)
     */
    public void exportToJpg(String outputFile) throws IOException {
        MutableGraph g = buildGraph();
        
        // Render and save as PNG with configurable resolution
        Graphviz.fromGraph(g)
                .width(imageWidth)
                .render(Format.PNG)
                .toFile(new File(outputFile));
        System.out.println("Image file exported to: " + outputFile + " (width: " + imageWidth + "px)");
    }
    
    /**
     * Build the graph model for GraphViz
     */
    private MutableGraph buildGraph() {
        MutableGraph g = mutGraph("ClassRelationships").setDirected(true)
                .graphAttrs().add(Rank.dir(Rank.RankDir.LEFT_TO_RIGHT))
                .nodeAttrs().add(Shape.RECTANGLE, Style.FILLED, Font.name("Arial"));
        
        Map<String, MutableNode> nodes = new HashMap<>();
        Map<String, String> innerToOuterClassMap = new HashMap<>();
        
        // Step 1: Create nodes only for outer classes and map inner classes to their outer classes
        for (String className : graph.getNodes().keySet()) {
            // Check if this is an inner class
            if (className.contains("$")) {
                String outerClassName = className.substring(0, className.indexOf("$"));
                innerToOuterClassMap.put(className, outerClassName);
                
                // If we don't already have the outer class, create a node for it
                if (!nodes.containsKey(outerClassName) && !graph.getNodes().containsKey(outerClassName)) {
                    String displayName = getSimpleClassName(outerClassName);
                    MutableNode node = mutNode(displayName).add(Label.of(displayName));
                    nodes.put(outerClassName, node);
                    g.add(node);
                }
            } else {
                // This is an outer class, create a node
                String displayName = getSimpleClassName(className);
                MutableNode node = mutNode(displayName).add(Label.of(displayName));
                nodes.put(className, node);
                g.add(node);
            }
        }
        
        // Track already created edges to avoid duplicates
        Map<String, Set<String>> existingEdges = new HashMap<>();
        
        // Track relationship counts between classes
        Map<String, Map<String, Map<RelationshipType, Integer>>> relationshipCounts = new HashMap<>();
        
        // Step 2: Process relationships, mapping inner classes to their outer classes
        for (String className : graph.getNodes().keySet()) {
            ClassNode node = graph.getNodes().get(className);
            String effectiveSourceClass = className;
            
            // If this is an inner class, map to outer class
            if (innerToOuterClassMap.containsKey(className)) {
                effectiveSourceClass = innerToOuterClassMap.get(className);
            }
            
            MutableNode sourceNode = nodes.get(effectiveSourceClass);
            
            // Group relationships by target class
            Map<String, Set<RelationshipType>> relationshipsByTarget = new HashMap<>();
            
            // Track counts of each relationship type between source and target
            for (Relationship rel : node.getRelationships()) {
                String targetClass = rel.getTargetClass();
                String effectiveTargetClass = targetClass;
                
                // If target is an inner class, map to its outer class
                if (innerToOuterClassMap.containsKey(targetClass)) {
                    effectiveTargetClass = innerToOuterClassMap.get(targetClass);
                }
                
                // Skip self-references
                if (effectiveSourceClass.equals(effectiveTargetClass)) {
                    continue;
                }
                
                // Add relationship type to the set
                relationshipsByTarget
                    .computeIfAbsent(effectiveTargetClass, k -> new HashSet<>())
                    .add(rel.getType());
                
                // Track relationship counts by type
                relationshipCounts
                    .computeIfAbsent(effectiveSourceClass, k -> new HashMap<>())
                    .computeIfAbsent(effectiveTargetClass, k -> new HashMap<>())
                    .merge(rel.getType(), rel.getCount(), Integer::sum); // 使用实际出现次数(getCount)而不是简单计数
            }
            
            // Create edges for each target class
            for (Map.Entry<String, Set<RelationshipType>> targetEntry : relationshipsByTarget.entrySet()) {
                String effectiveTargetClass = targetEntry.getKey(); // This is already the effective target class from above
                Set<RelationshipType> types = targetEntry.getValue();
                
                // Skip if we've already created this edge
                if (existingEdges.computeIfAbsent(effectiveSourceClass, k -> new HashSet<>()).contains(effectiveTargetClass)) {
                    continue;
                }
                
                // Mark this edge as created
                existingEdges.get(effectiveSourceClass).add(effectiveTargetClass);
                
                MutableNode targetNode = nodes.get(effectiveTargetClass);
                
                // Choose the "most important" relationship type to display
                RelationshipType primaryType = getPrimaryRelationshipType(types);
                
                // Get color for this relationship type
                Color color = relationshipColors.getOrDefault(primaryType, Color.BLACK);
                
                // Calculate the total count of relationships between these classes
                int totalCount = 0;
                Map<RelationshipType, Integer> typeCounts = relationshipCounts
                    .getOrDefault(effectiveSourceClass, Collections.emptyMap())
                    .getOrDefault(effectiveTargetClass, Collections.emptyMap());
                
                for (Integer count : typeCounts.values()) {
                    totalCount += count;
                }
                
                // Combine all relationship types into the label with counts
                String label = types.size() == 1 ? 
                    primaryType.toString().toLowerCase() + " (" + typeCounts.getOrDefault(primaryType, 1) + ")" : 
                    getMultipleRelationshipLabel(types, typeCounts);
                
                // Add edge with appropriate style and weight based on count
                sourceNode.addLink(
                    to(targetNode)
                        .with(
                            Style.SOLID,
                            color,
                            Label.of(label),
                            Arrow.NORMAL,
                            // Add thickness based on relationship count (min 1.0, max 5.0)
                            Style.lineWidth(Math.min(1.0 + (totalCount * 0.5), 5.0))
                        )
                );
            }
        }
        
        return g;
    }
    
    /**
     * Get the primary relationship type from a set of types
     * We prioritize certain relationship types over others
     */
    private RelationshipType getPrimaryRelationshipType(Set<RelationshipType> types) {
        // Priority order of relationship types
        RelationshipType[] priorityOrder = {
            RelationshipType.EXTENDS,
            RelationshipType.IMPLEMENTS,
            RelationshipType.ASSOCIATES,
            RelationshipType.INJECTS,
            RelationshipType.CREATES,
            RelationshipType.CALLS,
            RelationshipType.USES,
            RelationshipType.ANNOTATED_WITH,
            RelationshipType.REFERENCES,
            RelationshipType.DEPENDS_ON
        };
        
        for (RelationshipType type : priorityOrder) {
            if (types.contains(type)) {
                return type;
            }
        }
        
        // Default to the first type in the set if none of our priorities match
        return types.iterator().next();
    }
    
    /**
     * Create a label for an edge with multiple relationship types
     */
    private String getMultipleRelationshipLabel(Set<RelationshipType> types, Map<RelationshipType, Integer> counts) {
        StringBuilder sb = new StringBuilder();
        boolean first = true;
        
        // Sort types by priority
        List<RelationshipType> sortedTypes = new ArrayList<>(types);
        sortedTypes.sort(this::compareRelationshipTypes);
        
        for (RelationshipType type : sortedTypes) {
            if (!first) {
                sb.append(", ");
            }
            sb.append(type.toString().toLowerCase());
            
            // Add count in parentheses
            int count = counts.getOrDefault(type, 1);
            sb.append(" (").append(count).append(")");
            
            first = false;
        }
        
        return sb.toString();
    }
    
    /**
     * Compare relationship types by priority
     */
    private int compareRelationshipTypes(RelationshipType t1, RelationshipType t2) {
        // Priority order of relationship types (same as in getPrimaryRelationshipType)
        List<RelationshipType> priorityOrder = Arrays.asList(
            RelationshipType.EXTENDS,
            RelationshipType.IMPLEMENTS,
            RelationshipType.ASSOCIATES,
            RelationshipType.INJECTS,
            RelationshipType.CREATES,
            RelationshipType.CALLS,
            RelationshipType.USES,
            RelationshipType.ANNOTATED_WITH,
            RelationshipType.REFERENCES,
            RelationshipType.DEPENDS_ON
        );
        
        int idx1 = priorityOrder.indexOf(t1);
        int idx2 = priorityOrder.indexOf(t2);
        
        // If both are found in the priority list, compare their positions
        if (idx1 >= 0 && idx2 >= 0) {
            return Integer.compare(idx1, idx2);
        }
        
        // If only one is found, it has higher priority
        if (idx1 >= 0) return -1;
        if (idx2 >= 0) return 1;
        
        // If neither is found, compare by name
        return t1.toString().compareTo(t2.toString());
    }
    
    /**
     * Get simple class name from fully qualified name
     */
    private String getSimpleClassName(String className) {
        // First extract from package
        int lastDot = className.lastIndexOf('.');
        String nameWithoutPackage = lastDot > 0 ? className.substring(lastDot + 1) : className;
        
        // If this is an inner class (contains $), format it as OuterClass.InnerClass
        if (nameWithoutPackage.contains("$")) {
            return nameWithoutPackage.replace("$", ".");
        }
        
        return nameWithoutPackage;
    }
    
    /**
     * Create a label for an edge with multiple relationship types
     * @deprecated Use getMultipleRelationshipLabel(Set<RelationshipType>, Map<RelationshipType, Integer>) instead
     */
    @Deprecated
    private String getMultipleRelationshipLabel(Set<RelationshipType> types) {
        StringBuilder sb = new StringBuilder();
        boolean first = true;
        
        for (RelationshipType type : types) {
            if (!first) {
                sb.append(", ");
            }
            sb.append(type.toString().toLowerCase());
            first = false;
        }
        
        return sb.toString();
    }
} 