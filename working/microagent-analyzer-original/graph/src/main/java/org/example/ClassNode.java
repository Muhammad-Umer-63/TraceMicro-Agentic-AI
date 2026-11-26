package org.example;

import java.util.ArrayList;
import java.util.List;

/**
 * Represents a class node in the relationship graph
 */
public class ClassNode {
    private String className;
    private List<Relationship> relationships = new ArrayList<>();
    
    public ClassNode(String className) {
        this.className = className;
    }
    
    /**
     * Add a relationship from this class to another class
     */
    public void addRelationship(String targetClass, RelationshipType type) {
        // Check if this relationship already exists
        for (Relationship rel : relationships) {
            if (rel.getTargetClass().equals(targetClass) && rel.getType() == type) {
                // Increment count instead of skipping
                rel.incrementCount();
                return;
            }
        }
        
        // Add the new relationship
        relationships.add(new Relationship(targetClass, type));
    }
    
    /**
     * Add a relationship object directly
     */
    public void addRelationship(Relationship relationship) {
        // Check if this relationship already exists
        for (Relationship rel : relationships) {
            if (rel.getTargetClass().equals(relationship.getTargetClass()) && 
                rel.getType() == relationship.getType()) {
                // Increment count instead of skipping
                rel.incrementCount();
                return;
            }
        }
        
        // Add the new relationship
        relationships.add(relationship);
    }
    
    /**
     * Get all relationships for this class
     */
    public List<Relationship> getRelationships() {
        return relationships;
    }
    
    /**
     * Set the relationships for this class
     */
    public void setRelationships(List<Relationship> relationships) {
        this.relationships = relationships;
    }
    
    /**
     * Get the class name
     */
    public String getClassName() {
        return className;
    }
} 